"""High level helpers for interacting with ShotGrid entities.

This in-memory implementation mirrors the ergonomics of the real ShotGrid API
while keeping tests fast and deterministic.
"""

import json
import logging
import time
import yaml
from collections import defaultdict
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast, Mapping, Optional, Sequence, TypedDict, TypeVar

log = logging.getLogger(__name__)

__all__ = [
    "EntityStore",
    "HierarchyTemplate",
    "RetryPolicy",
    "ShotgridClient",
    "ShotgridOperationError",
    "TemplateNode",
    "EntityPayload",
    "Project",
    "Version",
    "Playlist",
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
    playlist_name: str
    version_ids: list[int]


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


class Playlist(TypedDict):
    """Internal representation of a ShotGrid Playlist."""

    id: int
    type: str
    name: str
    playlist_name: str
    project: str
    project_id: int
    version_ids: list[int]


TEntity = TypeVar("TEntity", bound=EntityPayload)

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
        if not store:
            return 1
        return max(store.keys()) + 1

    def list(self, entity_type: str) -> list[EntityPayload]:
        return list(self._entities.get(entity_type, {}).values())


# ---------------------------------------------------------------------------
# Hierarchy template
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateNode:
    """Describe an entity and its children used in hierarchy templates."""

    entity_type: str
    attributes: dict[str, Any]
    children: Sequence["TemplateNode"] = ()

    def expand(self) -> list["TemplateNode"]:
        nodes = [self]
        for child in self.children:
            nodes.extend(child.expand())
        return nodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_type": self.entity_type,
            "attributes": dict(self.attributes),
            "children": [child.to_dict() for child in self.children],
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "TemplateNode":
        if not isinstance(data, Mapping):
            raise ValueError("Template node must be a mapping of attributes.")

        entity_type = data.get("entity_type")
        if not isinstance(entity_type, str) or not entity_type:
            raise ValueError("Template node must define an 'entity_type'.")

        attributes = data.get("attributes", {})
        if not isinstance(attributes, Mapping):
            raise ValueError("Template node 'attributes' must be a mapping.")

        children_data = data.get("children", [])
        if not isinstance(children_data, Sequence):
            raise ValueError("Template node 'children' must be a sequence.")

        children = tuple(
            TemplateNode.from_dict(cast(Mapping[str, Any], child))
            for child in children_data
        )

        return TemplateNode(
            entity_type=entity_type,
            attributes=dict(attributes),
            children=children,
        )


@dataclass(frozen=True)
class HierarchyTemplate:
    """Reusable structure for creating entity hierarchies."""

    name: str
    roots: Sequence[TemplateNode]

    def expand(self) -> list[TemplateNode]:
        nodes: list[TemplateNode] = []
        for root in self.roots:
            nodes.extend(root.expand())
        return nodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "roots": [node.to_dict() for node in self.roots],
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "HierarchyTemplate":
        if not isinstance(data, Mapping):
            raise ValueError("Hierarchy template definition must be a mapping.")

        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Hierarchy template must include a non-empty 'name'.")

        roots_data = data.get("roots", [])
        if not isinstance(roots_data, Sequence):
            raise ValueError("Hierarchy template 'roots' must be a sequence.")

        roots = tuple(
            TemplateNode.from_dict(cast(Mapping[str, Any], node)) for node in roots_data
        )

        return HierarchyTemplate(name=name, roots=roots)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ShotgridClient:
    """A lightweight yet feature rich in-memory ShotGrid client.

    The client mirrors key aspects of the ShotGrid API while keeping
    operations synchronous and deterministic for tests. Helper methods are
    provided for registering and querying versions, such as
    :meth:`register_version`, :meth:`list_versions`, and
    :meth:`list_versions_for_shot`, alongside playlist and hierarchy
    utilities.
    """

    def __init__(
        self,
        store: EntityStore | None = None,
        retry_policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._store = store or EntityStore()
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep or time.sleep

    # Template serialization helpers ---------------------------------

    @staticmethod
    def _template_format(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            return "yaml"
        return "json"

    @staticmethod
    def _dump_template_payload(path: Path, payload: Mapping[str, Any]) -> None:
        format_name = ShotgridClient._template_format(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("w", encoding="utf-8") as handle:
                if format_name == "yaml":
                    yaml.safe_dump(dict(payload), handle, sort_keys=True)
                else:
                    json.dump(payload, handle, indent=2, sort_keys=True)
        except OSError:
            raise

    @staticmethod
    def _load_template_payload(path: Path) -> Mapping[str, Any]:
        format_hint = ShotgridClient._template_format(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raise

        formats = [format_hint]
        if format_hint == "yaml":
            formats.append("json")
        else:
            formats.append("yaml")

        last_error: ValueError | None = None
        for format_name in formats:
            try:
                if format_name == "yaml":
                    payload = yaml.safe_load(raw)
                else:
                    payload = json.loads(raw)
            except Exception as exc:  # noqa: BLE001 - capture for diagnostics
                last_error = ValueError(str(exc))
                continue

            if not isinstance(payload, Mapping):
                raise ValueError("Hierarchy template file must contain an object.")

            return cast(Mapping[str, Any], payload)

        if last_error is not None:
            raise last_error
        raise ValueError("Hierarchy template file is empty.")

    def serialize_hierarchy_template(
        self, template: HierarchyTemplate
    ) -> dict[str, Any]:
        return template.to_dict()

    def deserialize_hierarchy_template(
        self, data: Mapping[str, Any]
    ) -> HierarchyTemplate:
        return HierarchyTemplate.from_dict(data)

    def save_hierarchy_template(self, template: HierarchyTemplate, path: Path) -> None:
        payload = self.serialize_hierarchy_template(template)
        target = path.expanduser()
        self._dump_template_payload(target, payload)

    def load_hierarchy_template(self, path: Path) -> HierarchyTemplate:
        source = path.expanduser()
        payload = self._load_template_payload(source)
        return self.deserialize_hierarchy_template(payload)

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
                last_exc = exc
                attempts += 1
                if attempts >= self._retry_policy.max_attempts:
                    log.error(
                        "shotgrid.retry_exhausted function=%s attempts=%s error=%s",
                        getattr(func, "__name__", str(func)),
                        attempts,
                        last_exc,
                    )
                    raise ShotgridOperationError(str(exc)) from exc

                log.warning(
                    "shotgrid.retry function=%s attempts=%s delay=%.3f error=%s",
                    getattr(func, "__name__", str(func)),
                    attempts,
                    delay,
                    last_exc,
                )
                self._sleep(delay)
                delay = (
                    min(delay * 2, self._retry_policy.max_delay)
                    + self._retry_policy.jitter
                )
        assert False, "Retry loop should either return or raise"

    # Bulk helpers -----------------------------------------------------

    def _resolve_entity_type(self, entity_type: str) -> str:
        normalized = entity_type.strip()
        if not normalized:
            raise ValueError("entity_type must be provided")
        return normalized

    def bulk_create_entities(
        self, entity_type: str, payloads: Iterable[dict[str, Any]]
    ) -> list[EntityPayload]:
        etype = self._resolve_entity_type(entity_type)
        created: list[EntityPayload] = []

        def _create_single(payload: dict[str, Any]) -> EntityPayload:
            next_id = self._store.next_id(etype)
            base: EntityPayload = {"id": next_id, "type": etype}
            base.update(cast(EntityPayload, payload))
            return self._store.add(etype, base)

        for payload in payloads:
            created.append(self._execute_with_retry(_create_single, payload))
        return created

    def bulk_update_entities(
        self, entity_type: str, updates: Iterable[dict[str, Any]]
    ) -> list[EntityPayload]:
        etype = self._resolve_entity_type(entity_type)
        updated: list[EntityPayload] = []

        def _update_single(update: dict[str, Any]) -> EntityPayload:
            if "id" not in update:
                raise ValueError("update payload must contain an 'id' field")
            update_copy = dict(update)
            entity_id = int(update_copy.pop("id"))
            return self._store.update(etype, entity_id, update_copy)

        for payload in updates:
            updated.append(self._execute_with_retry(_update_single, payload))
        return updated

    def bulk_delete_entities(self, entity_type: str, entity_ids: Iterable[int]) -> None:
        etype = self._resolve_entity_type(entity_type)

        def _delete_single(entity_id: int) -> None:
            self._store.delete(etype, entity_id)

        for entity_id in entity_ids:
            self._execute_with_retry(_delete_single, int(entity_id))

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
        context = context or {}

        for node in template.expand():
            attrs = {**node.attributes, **context}
            if "project_id" not in attrs:
                attrs["project_id"] = project["id"]
            created = self.bulk_create_entities(node.entity_type, [attrs])[0]
            results[node.entity_type].append(created)

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

    def list_versions_for_shot(
        self,
        project_name: str,
        shot_code: str,
        *,
        statuses: Sequence[str | None] | None = None,
    ) -> list[Version]:
        """Return versions filtered by project, shot, and optional statuses."""

        if not project_name:
            raise ValueError("project_name must be supplied")
        if not shot_code:
            raise ValueError("shot_code must be supplied")

        normalized_statuses: set[str] | None = None
        if statuses is not None:
            normalized_statuses = {
                "" if status is None else str(status).strip().lower()
                for status in statuses
            }

        filtered: list[Version] = []
        for version in self.list_versions():
            if version.get("project") != project_name:
                continue
            if version.get("shot") != shot_code:
                continue

            if normalized_statuses is not None:
                raw_status = version.get("status")
                normalized = (
                    "" if raw_status is None else str(raw_status).strip().lower()
                )
                if normalized not in normalized_statuses:
                    continue

            filtered.append(version)

        return filtered

    def get_version_by_id(self, version_id: int) -> Version | None:
        """Return a version registered with the in-memory store."""

        payload = self._store.get("Version", int(version_id))
        return cast(Version | None, payload)

    def get_approved_versions(
        self, project_name: str, episodes: list[str] | None = None
    ) -> list[dict[str, object]]:
        """Return approved versions filtered by project and optional episodes."""

        episode_filters = (
            [
                episode.strip().lower()
                for episode in episodes
                if episode and episode.strip()
            ]
            if episodes
            else []
        )

        approved: list[dict[str, object]] = []
        for version in self.list_versions():
            if version.get("project") != project_name:
                continue
            shot_code = version.get("shot", "")
            shot_code_text = str(shot_code)
            if episode_filters:
                shot_code_normalized = shot_code_text.lower()
                if not any(
                    filter_value in shot_code_normalized
                    for filter_value in episode_filters
                ):
                    continue
            approved.append(
                {
                    "shot": shot_code,
                    "version": version.get("code", 0),
                    "file_path": version.get("path", ""),
                    "status": "apr",
                }
            )
        return approved

    # Playlist helpers -------------------------------------------------

    def _playlist_key(self, project_name: str, playlist_name: str) -> str:
        if not project_name:
            raise ValueError("project_name must be provided")
        if not playlist_name:
            raise ValueError("playlist_name must be provided")
        return f"{project_name}::{playlist_name}"

    def register_playlist(
        self,
        project_name: str,
        playlist_name: str,
        version_ids: Sequence[int],
    ) -> Playlist:
        """Register a playlist referencing existing versions."""

        project = self.get_or_create_project(project_name)

        missing_versions = [
            version_id
            for version_id in version_ids
            if self.get_version_by_id(int(version_id)) is None
        ]
        if missing_versions:
            missing = ", ".join(str(vid) for vid in missing_versions)
            raise ValueError(f"Unknown version ids in playlist: {missing}")

        key = self._playlist_key(project["name"], playlist_name)

        def _register() -> Playlist:
            payload: EntityPayload = {
                "id": self._store.next_id("Playlist"),
                "type": "Playlist",
                "name": key,
                "playlist_name": playlist_name,
                "project": project["name"],
                "project_id": project["id"],
                "version_ids": [int(v) for v in version_ids],
            }
            return cast(Playlist, self._store.add("Playlist", payload))

        return cast(Playlist, self._execute_with_retry(_register))

    def get_playlist(self, project_name: str, playlist_name: str) -> Playlist | None:
        """Retrieve a registered playlist."""

        key = self._playlist_key(project_name, playlist_name)
        playlist = self._store.get_by_unique_key("Playlist", key)
        return cast(Playlist | None, playlist)

    def list_playlists(self, project_name: str | None = None) -> list[Playlist]:
        """Return playlists, optionally filtered by project name."""

        playlists = [
            cast(Playlist, playlist) for playlist in self._store.list("Playlist")
        ]
        if project_name is None:
            return playlists
        return [
            playlist
            for playlist in playlists
            if playlist.get("project") == project_name
        ]
