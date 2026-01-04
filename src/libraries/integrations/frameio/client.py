"""High level helpers for interacting with Frame.io projects.

This in-memory client mirrors the ergonomics of the ShotGrid helpers while
focusing on Frame.io concepts such as projects, folders, assets, and review
links. It is intentionally synchronous and deterministic to keep tests fast
while providing a realistic façade for higher-level features.
"""

from __future__ import annotations

import json
import logging
import time
import yaml
from collections import defaultdict
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, TypedDict, TypeVar, cast

log = logging.getLogger(__name__)

__all__ = [
    "EntityStore",
    "HierarchyTemplate",
    "RetryPolicy",
    "FrameioClient",
    "FrameioOperationError",
    "TemplateNode",
    "EntityPayload",
    "Team",
    "Project",
    "Folder",
    "Asset",
    "ReviewLink",
]


class EntityPayload(TypedDict, total=False):
    """Minimal representation of an entity stored in memory."""

    id: int
    type: str
    name: str
    project: str
    project_id: int
    team: str | None
    team_id: int | None
    folder_name: str
    folder_path: str | None
    folder_id: int | None
    parent_id: int | None
    path: str
    description: str
    asset_ids: list[int]


class Team(TypedDict):
    id: int
    name: str


class Project(TypedDict):
    id: int
    name: str
    team_id: int | None
    team: str | None


class Folder(TypedDict):
    id: int
    name: str
    folder_name: str
    project: str
    project_id: int
    parent_id: int | None
    path: str


class Asset(TypedDict):
    id: int
    name: str
    project: str
    project_id: int
    folder_id: int | None
    folder_path: str | None
    path: str
    description: str


class ReviewLink(TypedDict):
    id: int
    type: str
    name: str
    project: str
    project_id: int
    asset_ids: list[int]


TEntity = TypeVar("TEntity", bound=EntityPayload)


@dataclass
class FrameioOperationError(RuntimeError):
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
        unique_key = entity.get("name") or entity.get("path")
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

        entity = dict(store[entity_id])
        entity.update(data)
        store[entity_id] = cast(EntityPayload, entity)

        index = self._indices.get(entity_type)
        if index is not None:
            for key in list(index):
                if index[key] == entity_id:
                    del index[key]
            unique_key = entity.get("name") or entity.get("path")
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
            unique_key = entity.get("name") or entity.get("path")
            if unique_key is not None:
                key_text = str(unique_key)
                if key_text and key_text in index:
                    del index[key_text]

    def next_id(self, entity_type: str) -> int:
        store = self._ensure_type(entity_type)
        if not store:
            return 1
        return max(store.keys()) + 1

    def list(self, entity_type: str) -> list[EntityPayload]:
        return list(self._entities.get(entity_type, {}).values())


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


class FrameioClient:
    """A lightweight yet feature rich in-memory Frame.io client."""

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

    def _load_template_payload(self, path: Path) -> Mapping[str, Any]:
        with path.open("r", encoding="utf-8") as handle:
            if path.suffix.lower() in {".yaml", ".yml"}:
                return cast(Mapping[str, Any], yaml.safe_load(handle) or {})
            return cast(Mapping[str, Any], json.load(handle))

    def serialize_hierarchy_template(
        self, template: HierarchyTemplate
    ) -> dict[str, Any]:
        return template.to_dict()

    def deserialize_hierarchy_template(
        self, payload: Mapping[str, Any]
    ) -> HierarchyTemplate:
        return HierarchyTemplate.from_dict(payload)

    def save_hierarchy_template(self, template: HierarchyTemplate, path: Path) -> None:
        serialized = self.serialize_hierarchy_template(template)
        destination = path.expanduser()
        with destination.open("w", encoding="utf-8") as handle:
            if destination.suffix.lower() in {".yaml", ".yml"}:
                yaml.safe_dump(serialized, handle, sort_keys=False)
            else:
                json.dump(serialized, handle, indent=2)

    def load_hierarchy_template(self, path: Path) -> HierarchyTemplate:
        source = path.expanduser()
        payload = self._load_template_payload(source)
        return self.deserialize_hierarchy_template(payload)

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
                        "frameio.retry_exhausted function=%s attempts=%s error=%s",
                        getattr(func, "__name__", str(func)),
                        attempts,
                        last_exc,
                    )
                    raise FrameioOperationError(str(exc)) from exc

                log.warning(
                    "frameio.retry function=%s attempts=%s delay=%.3f error=%s",
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

    # Project helpers --------------------------------------------------

    def _find_team(self, name: str) -> Team | None:
        team = self._store.get_by_unique_key("Team", name)
        return cast(Team | None, team)

    def get_or_create_team(self, name: str) -> Team:
        if not name:
            raise ValueError("team name must be provided")
        team = self._find_team(name)
        if team is not None:
            return team

        def _create() -> Team:
            payload: EntityPayload = {
                "id": self._store.next_id("Team"),
                "type": "Team",
                "name": name,
            }
            return cast(Team, self._store.add("Team", payload))

        return cast(Team, self._execute_with_retry(_create))

    def _find_project(self, name: str) -> Project | None:
        proj = self._store.get_by_unique_key("Project", name)
        return cast(Project | None, proj)

    def get_or_create_project(self, name: str, *, team: str | None = None) -> Project:
        if not name:
            raise ValueError("project name must be provided")

        project = self._find_project(name)
        if project is not None:
            return project

        team_payload: Team | None = None
        if team:
            team_payload = self.get_or_create_team(team)

        def _create() -> Project:
            payload: EntityPayload = {
                "id": self._store.next_id("Project"),
                "type": "Project",
                "name": name,
                "team": team_payload["name"] if team_payload else None,
                "team_id": team_payload["id"] if team_payload else None,
            }
            return cast(Project, self._store.add("Project", payload))

        return cast(Project, self._execute_with_retry(_create))

    # Folder helpers ---------------------------------------------------

    def _folder_key(self, project: Project, folder_path: str) -> str:
        return f"{project['name']}::{folder_path}"

    def _ensure_folder(
        self, project: Project, folder_path: str | None
    ) -> Folder | None:
        if not folder_path:
            return None

        normalized = "/".join(
            segment.strip()
            for segment in folder_path.strip("/ ").split("/")
            if segment.strip()
        )
        if not normalized:
            return None

        parent_id: int | None = None
        accumulated: list[str] = []
        folder: Folder | None = None

        for segment in normalized.split("/"):
            accumulated.append(segment)
            current_path = "/".join(accumulated)
            key = self._folder_key(project, current_path)
            existing = self._store.get_by_unique_key("Folder", key)
            if existing:
                folder = cast(Folder, existing)
                parent_id = folder.get("id")
                continue

            def _create() -> Folder:
                payload: EntityPayload = {
                    "id": self._store.next_id("Folder"),
                    "type": "Folder",
                    "name": key,
                    "folder_name": segment,
                    "project": project["name"],
                    "project_id": project["id"],
                    "parent_id": parent_id,
                    "path": current_path,
                }
                return cast(Folder, self._store.add("Folder", payload))

            folder = cast(Folder, self._execute_with_retry(_create))
            parent_id = folder["id"]

        return folder

    # Asset helpers ----------------------------------------------------

    def register_asset(
        self,
        project_name: str,
        file_path: Path,
        *,
        folder_path: str | None = None,
        description: str | None = None,
        team: str | None = None,
    ) -> Asset:
        if not project_name:
            raise ValueError("project_name must be supplied")

        project = self.get_or_create_project(project_name, team=team)
        folder = self._ensure_folder(project, folder_path)

        def _register() -> Asset:
            payload: EntityPayload = {
                "id": self._store.next_id("Asset"),
                "type": "Asset",
                "name": file_path.stem,
                "project": project["name"],
                "project_id": project["id"],
                "folder_id": folder["id"] if folder else None,
                "folder_path": folder["path"] if folder else None,
                "path": str(file_path),
                "description": description or "",
            }
            return cast(Asset, self._store.add("Asset", payload))

        return cast(Asset, self._execute_with_retry(_register))

    def list_assets(self) -> list[Asset]:
        return [cast(Asset, a) for a in self._store.list("Asset")]

    def list_assets_for_folder(
        self, project_name: str, folder_path: str
    ) -> list[Asset]:
        if not project_name:
            raise ValueError("project_name must be supplied")
        if not folder_path:
            raise ValueError("folder_path must be supplied")

        project = self.get_or_create_project(project_name)
        folder = self._ensure_folder(project, folder_path)
        if folder is None:
            return []

        return [
            asset for asset in self.list_assets() if asset["folder_id"] == folder["id"]
        ]

    def get_asset_by_id(self, asset_id: int) -> Asset | None:
        payload = self._store.get("Asset", int(asset_id))
        return cast(Asset | None, payload)

    # Review link helpers ----------------------------------------------

    def _review_link_key(self, project_name: str, name: str) -> str:
        if not project_name:
            raise ValueError("project_name must be provided")
        if not name:
            raise ValueError("name must be provided")
        return f"{project_name}::{name}"

    def register_review_link(
        self, project_name: str, name: str, asset_ids: Sequence[int]
    ) -> ReviewLink:
        project = self.get_or_create_project(project_name)

        missing_assets = [
            asset_id
            for asset_id in asset_ids
            if self.get_asset_by_id(int(asset_id)) is None
        ]
        if missing_assets:
            missing = ", ".join(str(aid) for aid in missing_assets)
            raise ValueError(f"Unknown asset ids in review link: {missing}")

        key = self._review_link_key(project["name"], name)

        def _register() -> ReviewLink:
            payload: EntityPayload = {
                "id": self._store.next_id("ReviewLink"),
                "type": "ReviewLink",
                "name": key,
                "project": project["name"],
                "project_id": project["id"],
                "asset_ids": [int(a) for a in asset_ids],
            }
            return cast(ReviewLink, self._store.add("ReviewLink", payload))

        return cast(ReviewLink, self._execute_with_retry(_register))

    def get_review_link(self, project_name: str, name: str) -> ReviewLink | None:
        key = self._review_link_key(project_name, name)
        link = self._store.get_by_unique_key("ReviewLink", key)
        return cast(ReviewLink | None, link)

    def ensure_review_link(
        self, project_name: str, name: str, asset_ids: Sequence[int]
    ) -> ReviewLink:
        existing = self.get_review_link(project_name, name)
        if existing is None:
            return self.register_review_link(project_name, name, asset_ids)

        merged_ids = list(dict.fromkeys([*existing.get("asset_ids", []), *asset_ids]))
        return cast(
            ReviewLink,
            self._store.update(
                "ReviewLink",
                existing["id"],
                {"asset_ids": [int(a) for a in merged_ids]},
            ),
        )

    def list_review_links(self, project_name: str | None = None) -> list[ReviewLink]:
        links = [cast(ReviewLink, link) for link in self._store.list("ReviewLink")]
        if project_name is None:
            return links
        return [link for link in links if link.get("project") == project_name]

    # Hierarchy helpers -------------------------------------------------

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
            if "project" not in attrs:
                attrs["project"] = project["name"]
            created = self.bulk_create_entities(node.entity_type, [attrs])[0]
            results[node.entity_type].append(created)

        return results
