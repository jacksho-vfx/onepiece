"""High level helpers for interacting with ShotGrid entities.

This in-memory implementation mirrors the ergonomics of the real ShotGrid API
while keeping tests fast and deterministic.
"""

import logging
import random
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, TypedDict, cast, TypeVar

log = logging.getLogger(__name__)

__all__ = [
    "EntityStore",
    "HierarchyTemplate",
    "RetryPolicy",
    "ShotgridClient",
    "ShotgridOperationError",
    "TemplateNode",
    "TemplateValue",
    "EntityPayload",
    "Project",
    "Version",
]


# ---------------------------------------------------------------------------
# Typed structures
# ---------------------------------------------------------------------------


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


class Project(TypedDict):
    """Internal structure used to describe a ShotGrid project."""

    id: int
    name: str


class Version(TypedDict):
    """Internal structure representing a registered ShotGrid Version."""

    id: int
    code: str
    project: str
    project_id: int
    shot: str
    path: str
    description: str


TEntity = TypeVar("TEntity", bound=EntityPayload)
T = TypeVar("T")
TemplateValue = Any | Callable[[dict[str, Any]], Any]

# ---------------------------------------------------------------------------
# Errors and retry config
# ---------------------------------------------------------------------------


@dataclass
class ShotgridOperationError(RuntimeError):
    """Raised when an operation cannot be completed after retries."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry helpers."""

    max_attempts: int = 3
    base_delay: float = 0.25
    max_delay: float = 2.0
    jitter: float = 0.05


# ---------------------------------------------------------------------------
# Entity storage
# ---------------------------------------------------------------------------


@dataclass
class EntityStore:
    """In-memory storage for arbitrary entity types."""

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

    def get(self, entity_type: str, entity_id: int) -> EntityPayload | None:
        return self._entities.get(entity_type, {}).get(entity_id)

    def get_by_unique_key(self, entity_type: str, value: str) -> EntityPayload | None:
        index = self._indices.get(entity_type, {})
        entity_id = index.get(value)
        if entity_id is None:
            return None
        return self.get(entity_type, entity_id)

    def update(
        self, entity_type: str, entity_id: int, data: dict[str, Any]
    ) -> EntityPayload:
        store = self._ensure_type(entity_type)
        if entity_id not in store:
            raise KeyError(f"{entity_type} {entity_id} does not exist")

        entity = dict(store[entity_id])  # copy to plain dict
        entity.update(data)

        # replace in store
        store[entity_id] = cast(EntityPayload, entity)

        index = self._indices.get(entity_type)
        if index is not None:
            for key in list(index):
                if index[key] == entity_id:
                    del index[key]
            unique_key = entity.get("name") or entity.get("code")
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

    def list(self, entity_type: str) -> list[EntityPayload]:
        return list(self._entities.get(entity_type, {}).values())


# ---------------------------------------------------------------------------
# Hierarchy template
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateNode:
    """Describe an entity and its children used in hierarchy templates."""

    entity_type: str
    attributes: Mapping[str, TemplateValue]
    children: Sequence["TemplateNode"] = ()
    context_updates: Mapping[str, TemplateValue] | None = None

    def expand(self) -> list["TemplateNode"]:
        nodes = [self]
        for child in self.children:
            nodes.extend(child.expand())
        return nodes


@dataclass(frozen=True)
class HierarchyTemplate:
    """Reusable structure for creating entity hierarchies."""

    name: str
    roots: Sequence[TemplateNode]


class _SafeFormatDict(dict[str, Any]):
    """`str.format_map` helper that leaves unknown keys untouched."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"

    def expand(self) -> list[TemplateNode]:
        nodes: list[TemplateNode] = []
        for root in self.roots:
            nodes.extend(root.expand())
        return nodes


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ShotgridClient:
    """A lightweight yet feature rich in-memory ShotGrid client."""

    def __init__(
        self,
        store: EntityStore | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
        batch_size: int = 50,
    ) -> None:
        self._store = store or EntityStore()
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep or time.sleep
        if batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")
        self._batch_size = batch_size

    # Project helpers --------------------------------------------------

    def _find_project(self, name: str) -> Project | None:
        proj = self._store.get_by_unique_key("Project", name)
        return cast(Project | None, proj)

    def _create_project(self, name: str) -> Project:
        next_id = self._store.next_id("Project")
        payload: EntityPayload = {"id": next_id, "name": name, "type": "Project"}
        return cast(Project, self._store.add("Project", payload))

    def get_or_create_project(self, name: str) -> Project:
        proj = self._find_project(name)
        if proj is not None:
            return proj
        return cast(Project, self._execute_with_retry(self._create_project, name))

    # Retry helpers ----------------------------------------------------

    def _execute_with_retry(
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        attempts = 0
        delay = self._retry_policy.base_delay
        last_exc: Optional[BaseException] = None
        while attempts < self._retry_policy.max_attempts:
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                attempts += 1
                last_exc = exc
                func_name = getattr(func, "__name__", str(func))
                if attempts >= self._retry_policy.max_attempts:
                    message = (
                        "Operation %s failed after %s attempts. Last error: %r"
                        % (func_name, attempts, last_exc)
                    )
                    log.error(
                        "shotgrid.retry_exhausted function=%s attempts=%s error=%s",
                        func_name,
                        attempts,
                        last_exc,
                    )
                    raise ShotgridOperationError(message) from exc

                wait_no_jitter = min(delay, self._retry_policy.max_delay)
                wait_time = wait_no_jitter + random.uniform(0.0, self._retry_policy.jitter)
                log.warning(
                    "shotgrid.retry_pending function=%s attempt=%s/%s wait=%.3f error=%s",
                    func_name,
                    attempts,
                    self._retry_policy.max_attempts,
                    wait_time,
                    last_exc,
                )
                self._sleep(wait_time)
                delay = min(delay * 2, self._retry_policy.max_delay)
        assert False, "Retry loop should either return or raise"

    # Bulk helpers -----------------------------------------------------

    def _resolve_entity_type(self, entity_type: str) -> str:
        normalized = entity_type.strip()
        if not normalized:
            raise ValueError("entity_type must be provided")
        return normalized

    def _iter_batches(self, items: Iterable[T], batch_size: int | None = None) -> Iterator[list[T]]:
        size = batch_size or self._batch_size
        batch: list[T] = []
        for item in items:
            batch.append(item)
            if len(batch) >= size:
                yield batch
                batch = []
        if batch:
            yield batch

    def _render_template_value(self, value: TemplateValue, *, context: dict[str, Any]) -> Any:
        if callable(value):
            return value(context)
        if isinstance(value, str):
            try:
                return value.format_map(_SafeFormatDict(context))
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    f"Failed to render template value {value!r}: {exc}"
                ) from exc
        return value

    def _render_template_mapping(
        self, mapping: Mapping[str, TemplateValue], *, context: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            key: self._render_template_value(value, context=context)
            for key, value in mapping.items()
        }

    def bulk_create_entities(
        self, entity_type: str, payloads: Iterable[dict[str, Any]]
    ) -> list[EntityPayload]:
        etype = self._resolve_entity_type(entity_type)
        created: list[EntityPayload] = []

        def _create_batch(batch: Sequence[dict[str, Any]]) -> list[EntityPayload]:
            start_id = self._store.next_id(etype)
            staged: list[EntityPayload] = []
            for index, payload in enumerate(batch):
                entity_payload: EntityPayload = {"id": start_id + index, "type": etype}
                entity_payload.update(cast(EntityPayload, payload))
                staged.append(entity_payload)

            created_batch: list[EntityPayload] = []
            try:
                for entity in staged:
                    created_batch.append(self._store.add(etype, entity))
            except Exception:
                for entity in created_batch:
                    self._store.delete(etype, entity["id"])
                raise
            log.debug(
                "shotgrid.bulk_create entity_type=%s size=%s", etype, len(created_batch)
            )
            return created_batch

        for chunk in self._iter_batches(payloads):
            batch = tuple(dict(payload) for payload in chunk)
            created.extend(self._execute_with_retry(_create_batch, batch))
        return created

    def bulk_update_entities(
        self, entity_type: str, updates: Iterable[dict[str, Any]]
    ) -> list[EntityPayload]:
        etype = self._resolve_entity_type(entity_type)
        updated: list[EntityPayload] = []

        def _update_batch(batch: Sequence[dict[str, Any]]) -> list[EntityPayload]:
            updated_batch: list[EntityPayload] = []
            originals: list[tuple[int, EntityPayload]] = []
            try:
                for item in batch:
                    if "id" not in item:
                        raise ValueError("update payload must contain an 'id' field")
                    update_copy = dict(item)
                    entity_id = int(update_copy.pop("id"))
                    original = self._store.get(etype, entity_id)
                    if original is not None:
                        originals.append((entity_id, cast(EntityPayload, dict(original))))
                    updated_batch.append(self._store.update(etype, entity_id, update_copy))
            except Exception:
                for entity_id, previous in reversed(originals):
                    previous_copy = dict(previous)
                    previous_copy.pop("id", None)
                    self._store.update(etype, entity_id, previous_copy)
                raise
            log.debug(
                "shotgrid.bulk_update entity_type=%s size=%s", etype, len(updated_batch)
            )
            return updated_batch

        for chunk in self._iter_batches(updates):
            batch = tuple(dict(payload) for payload in chunk)
            updated.extend(self._execute_with_retry(_update_batch, batch))
        return updated

    def bulk_delete_entities(self, entity_type: str, entity_ids: Iterable[int]) -> None:
        etype = self._resolve_entity_type(entity_type)

        def _delete_batch(batch: Sequence[int]) -> None:
            deleted: list[EntityPayload] = []
            try:
                for entity_id in batch:
                    entity = self._store.get(etype, entity_id)
                    if entity is not None:
                        deleted.append(cast(EntityPayload, dict(entity)))
                    self._store.delete(etype, entity_id)
            except Exception:
                for entity in deleted:
                    self._store.add(etype, entity)
                raise
            log.debug(
                "shotgrid.bulk_delete entity_type=%s size=%s", etype, len(batch)
            )

        for chunk in self._iter_batches(int(entity_id) for entity_id in entity_ids):
            batch = tuple(chunk)
            self._execute_with_retry(_delete_batch, batch)

    # Hierarchy templates ----------------------------------------------

    def apply_hierarchy_template(
        self,
        project_name: str,
        template: HierarchyTemplate,
        *,
        context: Optional[dict[str, Any]] = None,
    ) -> dict[str, list[EntityPayload]]:
        project = self.get_or_create_project(project_name)
        results: dict[str, list[EntityPayload]] = defaultdict(list)
        base_context: dict[str, Any] = {"project": project}
        if context:
            base_context.update(context)

        def _apply_node(
            node: TemplateNode,
            parent: EntityPayload | None,
            active_context: dict[str, Any],
        ) -> None:
            render_context = dict(active_context)
            render_context["parent"] = parent
            attributes = self._render_template_mapping(
                node.attributes, context=render_context
            )
            if "project_id" not in attributes:
                attributes["project_id"] = project["id"]
            created = self.bulk_create_entities(node.entity_type, [attributes])[0]
            results[node.entity_type].append(created)

            child_context = dict(render_context)
            child_context["entity"] = created
            if node.context_updates:
                child_context.update(
                    self._render_template_mapping(
                        node.context_updates, context=dict(child_context)
                    )
                )

            for child in node.children:
                _apply_node(child, created, child_context)

        for root in template.roots:
            _apply_node(root, None, dict(base_context))

        return results

    # Version helpers --------------------------------------------------

    def register_version(
        self,
        project_name: str,
        shot_code: str,
        file_path: Path,
        description: str | None = None,
    ) -> Version:
        if not project_name:
            raise ValueError("project_name must be supplied")
        if not shot_code:
            raise ValueError("shot_code must be supplied")

        project = self.get_or_create_project(project_name)

        def _register() -> Version:
            payload: EntityPayload = {
                "id": self._store.next_id("Version"),
                "type": "Version",
                "code": file_path.stem,
                "project": project["name"],
                "project_id": project["id"],
                "shot": shot_code,
                "path": str(file_path),
                "description": description or "",
            }
            return cast(Version, self._store.add("Version", payload))

        return cast(Version, self._execute_with_retry(_register))

    def list_versions(self) -> list[Version]:
        return [cast(Version, v) for v in self._store.list("Version")]
