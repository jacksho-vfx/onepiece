"""High level helpers for interacting with ShotGrid entities.

The original exercises shipped with a *very* small in-memory client that only
supported creating projects on demand and registering versions.  The user
request for bulk operations, retry handling and hierarchy templating required a
significant expansion of those capabilities.  The new implementation still
operates fully in-memory (keeping the tests fast and deterministic) but offers
an API that mirrors the ergonomics of the real project.

The main additions are:

``ShotgridClient.bulk_*``
    Efficient create/update/delete helpers that accept batches of entities and
    return the processed payloads.  The helpers share an exponential backoff
    retry policy that is also used by ``register_version`` and ``get_or_create``
    calls to mimic the production resilience layer.

``HierarchyTemplate``
    A declarative description of entity trees (for example project → episode →
    scene → shot).  Templates can be applied to a project to materialise the
    hierarchy with a single call – ideal when onboarding new shows.

The public API offered by the previous version remains intact which means the
existing ingest workflow keeps functioning.  The richer surface area is covered
by dedicated unit tests and extensive inline documentation so that future
changes have a solid foundation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Sequence, TypedDict

import logging

log = logging.getLogger(__name__)

__all__ = [
    "EntityStore",
    "HierarchyTemplate",
    "RetryPolicy",
    "ShotgridClient",
    "ShotgridOperationError",
    "TemplateNode",
]


class Project(TypedDict):
    """Internal structure used to describe a ShotGrid project."""

    id: int
    name: str


@dataclass
class ShotgridOperationError(RuntimeError):
    """Raised when an operation cannot be completed after retries."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for :func:`ShotgridClient._execute_with_retry`.

    Attributes
    ----------
    max_attempts:
        Maximum number of attempts (including the first try).
    base_delay:
        Initial delay (in seconds) used for exponential backoff.
    max_delay:
        Maximum delay between retries.
    jitter:
        Additional jitter applied to the computed delay.  The jitter helps to
        avoid thundering herds when multiple workers retry the same operation.
    """

    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 2.0
    jitter: float = 0.05


class EntityPayload(TypedDict, total=False):
    """Minimal representation of an entity stored in memory."""

    id: int
    type: str
    code: str
    name: str
    project: str
    project_id: int
    shot: str
    path: str
    description: str


@dataclass
class EntityStore:
    """In-memory storage for arbitrary entity types.

    The storage keeps track of the next ``id`` per entity type and supports
    retrieval, updates and deletion.  Entities are stored as dictionaries which
    mirrors how responses are returned by the real ShotGrid API.
    """

    _entities: MutableMapping[str, MutableMapping[int, EntityPayload]] = field(
        default_factory=lambda: defaultdict(dict)
    )
    _indices: MutableMapping[str, MutableMapping[str, int]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def _ensure_type(self, entity_type: str) -> MutableMapping[int, EntityPayload]:
        return self._entities[entity_type]

    def add(self, entity_type: str, entity: EntityPayload) -> EntityPayload:
        store = self._ensure_type(entity_type)
        store[entity["id"]] = entity
        index = self._indices[entity_type]
        unique_key = entity.get("name") or entity.get("code")
        if unique_key:
            index[str(unique_key)] = entity["id"]
        return entity

    def get(self, entity_type: str, entity_id: int) -> Optional[EntityPayload]:
        return self._entities.get(entity_type, {}).get(entity_id)

    def get_by_unique_key(self, entity_type: str, value: str) -> Optional[EntityPayload]:
        index = self._indices.get(entity_type, {})
        entity_id = index.get(value)
        if entity_id is None:
            return None
        return self.get(entity_type, entity_id)

    def update(
        self, entity_type: str, entity_id: int, data: Dict[str, Any]
    ) -> EntityPayload:
        store = self._ensure_type(entity_type)
        if entity_id not in store:
            raise KeyError(f"{entity_type} {entity_id} does not exist")
        store[entity_id].update(data)
        # Refresh index when name/code changes.
        index = self._indices.get(entity_type)
        if index is not None:
            for key in list(index):
                if index[key] == entity_id:
                    del index[key]
            unique_key = store[entity_id].get("name") or store[entity_id].get("code")
            if unique_key:
                index[str(unique_key)] = entity_id
        return store[entity_id]

    def delete(self, entity_type: str, entity_id: int) -> None:
        store = self._entities.get(entity_type)
        if not store or entity_id not in store:
            raise KeyError(f"{entity_type} {entity_id} does not exist")
        entity = store.pop(entity_id)
        index = self._indices.get(entity_type)
        if index:
            unique_key = entity.get("name") or entity.get("code")
            if unique_key and unique_key in index:
                del index[str(unique_key)]

    def next_id(self, entity_type: str) -> int:
        store = self._ensure_type(entity_type)
        return len(store) + 1

    def list(self, entity_type: str) -> List[EntityPayload]:
        return list(self._entities.get(entity_type, {}).values())


class Version(TypedDict):
    """Internal structure representing a registered ShotGrid Version."""

    id: int
    code: str
    project: str
    project_id: int
    shot: str
    path: str
    description: str


@dataclass
@dataclass(frozen=True)
class TemplateNode:
    """Describe an entity and its children used in hierarchy templates."""

    entity_type: str
    attributes: Dict[str, Any]
    children: Sequence["TemplateNode"] = ()

    def expand(self) -> List["TemplateNode"]:
        """Return a depth-first flattened list of nodes.

        The order ensures parents are always processed before their children.
        """

        nodes = [self]
        for child in self.children:
            nodes.extend(child.expand())
        return nodes


@dataclass(frozen=True)
class HierarchyTemplate:
    """Reusable structure for creating entity hierarchies."""

    name: str
    roots: Sequence[TemplateNode]

    def expand(self) -> List[TemplateNode]:
        nodes: List[TemplateNode] = []
        for root in self.roots:
            nodes.extend(root.expand())
        return nodes


class ShotgridClient:
    """A lightweight yet feature rich in-memory ShotGrid client."""

    def __init__(
        self,
        store: EntityStore | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._store = store or EntityStore()
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep or time.sleep

    # The following private helpers are patched in the unit tests so they are
    # intentionally minimal.
    def _find_project(self, name: str) -> Project | None:
        """Return the project matching *name* if one exists."""

        project = self._store.get_by_unique_key("Project", name)
        return project if project is not None else None

    def _create_project(self, name: str) -> Project:
        """Create a new project entry with a predictable payload."""

        next_id = self._store.next_id("Project")
        project: Project = {"id": next_id, "name": name}
        return self._store.add("Project", project)  # type: ignore[arg-type]

    def get_or_create_project(self, name: str) -> Project:
        """Fetch the project called *name* or create it if it doesn't exist."""

        project = self._find_project(name)
        if project is not None:
            return project
        return self._execute_with_retry(self._create_project, name)

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------
    def _execute_with_retry(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute ``func`` with retries using the configured policy."""

        attempts = 0
        delay = self._retry_policy.base_delay
        last_exc: Optional[BaseException] = None
        while attempts < self._retry_policy.max_attempts:
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - explicit retry handling
                last_exc = exc
                attempts += 1
                if attempts >= self._retry_policy.max_attempts:
                    log.error(
                        "shotgrid.retry_exhausted function=%s attempts=%s error=%s",
                        getattr(func, "__name__", str(func)),
                        attempts,
                        exc,
                    )
                    raise ShotgridOperationError(str(exc)) from exc

                log.warning(
                    "shotgrid.retry function=%s attempts=%s delay=%.3f error=%s",
                    getattr(func, "__name__", str(func)),
                    attempts,
                    delay,
                    exc,
                )
                self._sleep(delay)
                delay = min(delay * 2, self._retry_policy.max_delay) + self._retry_policy.jitter
        assert False, "Retry loop should either return or raise"

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------
    def _resolve_entity_type(self, entity_type: str) -> str:
        normalized = entity_type.strip()
        if not normalized:
            raise ValueError("entity_type must be provided")
        return normalized

    def bulk_create_entities(
        self,
        entity_type: str,
        payloads: Iterable[Dict[str, Any]],
    ) -> List[EntityPayload]:
        """Create entities in bulk and return the stored payloads."""

        etype = self._resolve_entity_type(entity_type)
        created: List[EntityPayload] = []

        def _create_single(payload: Dict[str, Any]) -> EntityPayload:
            next_id = self._store.next_id(etype)
            entity: EntityPayload = {"id": next_id, "type": etype, **payload}
            return self._store.add(etype, entity)

        for payload in payloads:
            created.append(self._execute_with_retry(_create_single, payload))
        return created

    def bulk_update_entities(
        self,
        entity_type: str,
        updates: Iterable[Dict[str, Any]],
    ) -> List[EntityPayload]:
        """Update entities in bulk.

        Each update dictionary must contain an ``id`` key identifying the
        target entity.  Additional key/value pairs are merged into the stored
        payload.
        """

        etype = self._resolve_entity_type(entity_type)
        updated: List[EntityPayload] = []

        def _update_single(update: Dict[str, Any]) -> EntityPayload:
            if "id" not in update:
                raise ValueError("update payload must contain an 'id' field")
            update_copy = dict(update)
            entity_id = int(update_copy.pop("id"))
            return self._store.update(etype, entity_id, update_copy)

        for payload in updates:
            updated.append(self._execute_with_retry(_update_single, payload))
        return updated

    def bulk_delete_entities(
        self,
        entity_type: str,
        entity_ids: Iterable[int],
    ) -> None:
        """Delete entities in bulk."""

        etype = self._resolve_entity_type(entity_type)

        def _delete_single(entity_id: int) -> None:
            self._store.delete(etype, entity_id)

        for entity_id in entity_ids:
            self._execute_with_retry(_delete_single, int(entity_id))

    # ------------------------------------------------------------------
    # Hierarchy templates
    # ------------------------------------------------------------------
    def apply_hierarchy_template(
        self,
        project_name: str,
        template: HierarchyTemplate,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[EntityPayload]]:
        """Materialise *template* under the project identified by ``project_name``.

        ``context`` values are merged into each node's attributes (without
        mutating the original template) which allows customisation per
        invocation.
        """

        project = self.get_or_create_project(project_name)
        results: Dict[str, List[EntityPayload]] = defaultdict(list)
        context = context or {}

        for node in template.expand():
            attrs = {**node.attributes, **context}
            if "project_id" not in attrs:
                attrs["project_id"] = project["id"]
            created = self.bulk_create_entities(node.entity_type, [attrs])[0]
            results[node.entity_type].append(created)

        return results

    # ------------------------------------------------------------------
    # Version helpers
    # ------------------------------------------------------------------
    def register_version(
        self,
        project_name: str,
        shot_code: str,
        file_path: Path,
        description: str | None = None,
    ) -> Version:
        """Register a new Version entry linked to *project_name* and *shot_code*."""

        if not project_name:
            raise ValueError("project_name must be supplied")
        if not shot_code:
            raise ValueError("shot_code must be supplied")

        project = self.get_or_create_project(project_name)

        def _register() -> Version:
            version: Version = {
                "id": self._store.next_id("Version"),
                "code": file_path.stem,
                "project": project["name"],
                "project_id": project["id"],
                "shot": shot_code,
                "path": str(file_path),
                "description": description if description else "",
            }
            return self._store.add("Version", version)  # type: ignore[arg-type]

        return self._execute_with_retry(_register)

    def list_versions(self) -> List[Version]:
        """Return all stored Version entries."""

        return self._store.list("Version")  # type: ignore[return-value]
