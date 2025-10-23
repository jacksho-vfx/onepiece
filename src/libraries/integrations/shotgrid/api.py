"""ShotGrid API client helpers used by the legacy library layer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urljoin

import requests
import structlog

from libraries.integrations.shotgrid.config import load_config
from libraries.integrations.shotgrid.models import (
    EpisodeData,
    PlaylistData,
    SceneData,
    ShotData,
    VersionData,
)

from libraries.integrations.shotgrid.models import PipelineStep, TaskCode, TaskData

log = structlog.get_logger(__name__)


def _version_view(
    *, summary: bool
) -> tuple[List[str], Callable[[Dict[str, Any]], Dict[str, Any]]]:
    """Return canonical Version fields and a parser for *summary* or *full* views."""

    fields: List[str] = [
        "code",
        "version_number",
        "sg_status_list",
        "sg_path_to_movie",
        "sg_uploaded_movie",
        "entity",
    ]
    if not summary:
        fields.extend(["description", "project"])

    def parse(record: Dict[str, Any]) -> Dict[str, Any]:
        attributes = record.get("attributes", {}) or {}
        relationships = record.get("relationships", {}) or {}

        entity_relationship = relationships.get("entity", {}) or {}
        entity_data = (
            entity_relationship.get("data", {})
            if isinstance(entity_relationship, dict)
            else {}
        )

        project_relationship = relationships.get("project", {}) or {}
        project_data = (
            project_relationship.get("data", {})
            if isinstance(project_relationship, dict)
            else {}
        )

        shot_name = (
            entity_data.get("name") or entity_data.get("code") or attributes.get("code")
        )

        file_path = attributes.get("sg_path_to_movie") or attributes.get(
            "sg_uploaded_movie"
        )

        summary_view = {
            "shot": shot_name,
            "version_number": attributes.get("version_number"),
            "file_path": file_path,
            "status": attributes.get("sg_status_list"),
            "code": attributes.get("code"),
        }

        if summary:
            return summary_view

        project_id = project_data.get("id") if isinstance(project_data, dict) else None

        return {
            "id": record.get("id"),
            "code": summary_view["code"],
            "shot": summary_view["shot"],
            "version_number": summary_view["version_number"],
            "file_path": summary_view["file_path"],
            "status": summary_view["status"],
            "description": attributes.get("description"),
            "project_id": project_id,
        }

    return fields, parse


class ShotGridError(Exception):
    """Raised when ShotGrid operations fail."""


class ShotGridClient:
    """REST client for Autodesk ShotGrid using xData models for create."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        script_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        cfg = load_config()
        self.base_url = base_url or cfg.base_url
        script_name = script_name or cfg.script_name
        api_key = api_key or cfg.api_key

        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._authenticate(script_name, api_key)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _authenticate(self, script_name: str, api_key: str) -> None:
        url = self._build_url("api", "v1", "auth", "access_token")
        payload = {
            "grant_type": "client_credentials",
            "client_id": script_name,
            "client_secret": api_key,
        }
        r = self._session.post(url, json=payload)
        if not r.ok:
            log.error("auth_failed", status=r.status_code, text=r.text)
            raise ShotGridError(f"Authentication failed: {r.status_code}")
        token = r.json()["access_token"]
        self._session.headers.update({"Authorization": f"Bearer {token}"})
        log.info("auth_success", base_url=str(self.base_url))

    def _get(self, entity: str, filters: List[Dict[str, Any]], fields: str) -> Any:
        url = self._build_url("api", "v1", f"entities/{entity.lower()}s")
        params = self._build_query_params(filters, fields)
        r = self._session.get(url, params=params)
        if not r.ok:
            log.error(
                "http_get_failed", entity=entity, status=r.status_code, text=r.text
            )
            raise ShotGridError(f"GET {entity} failed: {r.text}")
        return r.json().get("data", [])

    def _get_paginated(
        self,
        entity: str,
        filters: List[Dict[str, Any]],
        fields: str,
        page_size: int = 100,
    ) -> List[Dict[str, Any]]:
        url = self._build_url("api", "v1", f"entities/{entity.lower()}s")
        results: List[Dict[str, Any]] = []
        page = 1

        while True:
            params = self._build_query_params(
                filters,
                fields,
                extra={"page[number]": page, "page[size]": page_size},
            )
            response = self._session.get(url, params=params)
            if not response.ok:
                log.error(
                    "http_get_failed",
                    entity=entity,
                    status=response.status_code,
                    text=response.text,
                )
                raise ShotGridError(f"GET {entity} failed: {response.text}")

            payload = response.json()
            page_data = payload.get("data", []) or []
            results.extend(page_data)

            links = payload.get("links", {})
            next_link = links.get("next") if isinstance(links, dict) else None
            if not next_link:
                break
            page += 1

        return results

    def _post(
        self,
        entity: str,
        attributes: Dict[str, Any],
        relationships: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = self._build_url("api", "v1", f"entities/{entity.lower()}s")
        payload: Dict[str, Any] = {"data": {"type": entity, "attributes": attributes}}
        if relationships:
            payload["data"]["relationships"] = relationships
        r = self._session.post(url, json=payload)
        if not r.ok:
            log.error(
                "http_post_failed", entity=entity, status=r.status_code, text=r.text
            )
            raise ShotGridError(f"POST {entity} failed: {r.text}")
        return r.json()["data"]

    def _patch(
        self,
        entity: str,
        entity_id: int,
        attributes: Dict[str, Any],
        relationships: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = self._build_url("api", "v1", f"entity/{entity.lower()}s/{entity_id}")
        payload: Dict[str, Any] = {
            "data": {
                "type": entity,
                "id": entity_id,
                "attributes": attributes,
            }
        }
        if relationships:
            payload["data"]["relationships"] = relationships
        response = self._session.patch(url, json=payload)
        if not response.ok:
            log.error(
                "http_patch_failed",
                entity=entity,
                entity_id=entity_id,
                status=response.status_code,
                text=response.text,
            )
            raise ShotGridError(f"PATCH {entity} {entity_id} failed: {response.text}")
        return response.json()["data"]

    def _build_url(self, *segments: str) -> str:
        base = self.base_url.rstrip("/")
        path = "/".join(segment.strip("/") for segment in segments)
        return urljoin(f"{base}/", path)

    def _build_query_params(
        self,
        filters: List[Dict[str, Any]],
        fields: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"fields": fields}
        for idx, filter_entry in enumerate(filters):
            for key, value in filter_entry.items():
                params[f"filter[{idx}][{key}]"] = value
        if extra:
            params.update(extra)
        return params

    @staticmethod
    def _normalize_version(record: Dict[str, Any]) -> Dict[str, Any]:
        _, parser = _version_view(summary=False)
        return parser(record)

    def _get_single(
        self, entity: str, filters: List[Dict[str, Any]], fields: str = "id,name,code"
    ) -> Optional[Dict[str, Any]]:
        results = self._get(entity, filters, fields)
        return results[0] if results else None

    def _get_or_create_entity(
        self,
        fetch_entity: Callable[[], Any],
        create_entity: Callable[[], Any],
        *identifiers: object,
    ) -> Any:
        """Return an existing entity or create it when identifiers are present."""

        has_identifiers = all(identifiers) if identifiers else True
        entity = fetch_entity() if has_identifiers else None
        if entity:
            return entity
        if not has_identifiers:
            return None
        return create_entity()

    # ------------------------------------------------------------------ #
    # External helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls) -> "ShotGridClient":
        """
        Convenience constructor reading credentials from environment variables:
        SHOTGRID_URL, SHOTGRID_SCRIPT_NAME, SHOTGRID_API_KEY.
        """
        import os

        url = os.environ.get("SHOTGRID_URL")
        script = os.environ.get("SHOTGRID_SCRIPT_NAME")
        key = os.environ.get("SHOTGRID_API_KEY")

        if not all([url, script, key]):
            raise RuntimeError("Missing ShotGrid env vars.")
        return cls(base_url=url, script_name=script, api_key=key)

    # ------------------------------------------------------------------ #
    # Projects
    # ------------------------------------------------------------------ #
    def get_project(self, name: str) -> Any:
        return self._get_single("Project", [{"name": name}])

    def get_project_id_by_name(self, project_name: str) -> Optional[int]:
        log.debug("sg.get_project_id_by_name", project=project_name)
        result = self._get_single("Project", [{"name": project_name}])
        return result["id"] if result else None

    def create_project(self, project_name: str, template: str | None) -> Any:
        return self._post("Project", {"code": project_name, "template": template})

    def get_or_create_project(self, name: str, template: str | None) -> Any:
        return self._get_or_create_entity(
            lambda: self.get_project(name),
            lambda: self.create_project(name, template),
            name,
        )

    # ------------------------------------------------------------------ #
    # Playlists
    # ------------------------------------------------------------------ #
    def list_playlists(
        self, project_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return playlists optionally filtered by *project_name*."""

        filters: List[Dict[str, Any]] = []
        if project_name:
            project = self.get_project(project_name)
            if project and project.get("id") is not None:
                filters.append({"project": project["id"]})
            else:
                filters.append({"project": project_name})

        fields = "id,name,code,versions"
        return self._get_paginated("Playlist", filters, fields)

    def get_playlist_record(
        self,
        filters: Optional[List[Dict[str, Any]]] = None,
        fields: Sequence[str] | str = ("id", "name", "code", "versions"),
    ) -> Optional[Dict[str, Any]]:
        """Return a single playlist record using the provided *filters*."""

        resolved_filters = filters or []

        if isinstance(fields, str):
            field_param = fields
        else:
            field_param = ",".join(str(field).strip() for field in fields if field)

        if not field_param:
            field_param = "id,name,code"

        return self._get_single("Playlist", resolved_filters, field_param)

    def list_versions_raw(
        self,
        filters: Optional[List[Dict[str, Any]]] = None,
        fields: Sequence[str] | str | None = None,
        *,
        page_size: Optional[int] = 100,
    ) -> Any:
        """Return raw ShotGrid Version entities matching *filters*.

        Parameters
        ----------
        filters:
            ShotGrid filters encoded as dictionaries. When ``None`` an empty filter
            list is sent.
        fields:
            Field names to request. When ``None`` the full Version view is used.
            A comma separated string or iterable of field names is accepted for
            convenience.
        page_size:
            Desired page size when aggregating paginated results. Provide
            ``None`` to perform a single page request.
        """

        resolved_filters = filters or []

        if fields is None:
            field_names = _version_view(summary=False)[0]
        elif isinstance(fields, str):
            field_names = fields.split(",")
        else:
            field_names = list(fields)

        field_param = ",".join(field.strip() for field in field_names if field)

        if page_size is None:
            return self._get("Version", resolved_filters, field_param)

        return self._get_paginated(
            "Version", resolved_filters, field_param, page_size=page_size
        )

    def expand_playlist_versions(
        self, playlist_record: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Return normalised versions referenced by *playlist_record*."""

        relationships = (
            playlist_record.get("relationships", {})
            if isinstance(playlist_record, dict)
            else {}
        )
        versions_relationship = (
            relationships.get("versions", {}) if isinstance(relationships, dict) else {}
        )
        version_data = (
            versions_relationship.get("data", [])
            if isinstance(versions_relationship, dict)
            else []
        )

        version_ids: List[int] = []
        for entry in version_data or []:
            if not isinstance(entry, dict):
                continue
            identifier = entry.get("id")
            if identifier is None:
                continue
            try:
                version_ids.append(int(identifier))
            except (TypeError, ValueError):
                continue

        if not version_ids:
            return []

        filters = [{"id[$in]": ",".join(str(version_id) for version_id in version_ids)}]
        fields, parser = _version_view(summary=False)
        records = self.list_versions_raw(filters, fields, page_size=None)
        return [parser(record) for record in records]

    # ------------------------------------------------------------------ #
    # Episodes
    # ------------------------------------------------------------------ #
    def get_episode(self, project_id: int, name: str) -> Any:
        return self._get_single(
            "Episode", [{"project.id[$eq]": project_id}, {"code[$eq]": name}]
        )

    def create_episode(self, data: EpisodeData) -> Any:
        return self._post(
            data.entity_type,
            {"code": data.code, **data.extra},
            {"project": {"data": {"type": "Project", "id": data.project_id}}},
        )

    def get_or_create_episode(self, data: EpisodeData) -> Any:
        return self._get_or_create_entity(
            lambda: self.get_episode(data.project_id, data.code),
            lambda: self.create_episode(data),
            data.project_id,
            data.code,
        )

    # ------------------------------------------------------------------ #
    # Scenes
    # ------------------------------------------------------------------ #
    def get_scene(self, project_id: int, name: str) -> Any:
        return self._get_single("Scene", [{"project": project_id}, {"code": name}])

    def create_scene(self, data: SceneData) -> Any:
        return self._post(
            data.entity_type,
            {"code": data.code, **data.extra},
            {"project": {"data": {"type": "Project", "id": data.project_id}}},
        )

    def get_or_create_scene(self, data: SceneData) -> Any:
        return self._get_or_create_entity(
            lambda: self.get_scene(data.project_id, data.code),
            lambda: self.create_scene(data),
            data.project_id,
            data.code,
        )

    # ------------------------------------------------------------------ #
    # Shots
    # ------------------------------------------------------------------ #
    def get_shot(self, project_id: int, shot_name: str) -> Any:
        return self._get_single(
            "Shot",
            [{"project": project_id}, {"code": shot_name}],
            "id,code,sg_status_list",
        )

    def create_shot(self, data: ShotData) -> Any:
        rel = {"project": {"data": {"type": "Project", "id": data.project_id}}}
        if data.scene_id:
            rel["scene"] = {"data": {"type": "Scene", "id": data.scene_id}}
        return self._post(data.entity_type, {"code": data.code, **data.extra}, rel)

    def get_or_create_shot(self, data: ShotData) -> Any:
        return self._get_or_create_entity(
            lambda: self.get_shot(data.project_id, data.code),
            lambda: self.create_shot(data),
            data.project_id,
            data.code,
        )

    # ------------------------------------------------------------------ #
    # Versions
    # ------------------------------------------------------------------ #
    def get_versions_for_project(self, project_name: str) -> List[Dict[str, Any]]:
        """Return version summaries for the specified project."""

        project = self.get_project(project_name)
        if not project:
            log.warning("sg.project_not_found", project=project_name)
            return []

        project_id = project.get("id")
        filters = (
            [{"project": project_id}]
            if project_id is not None
            else [{"project": project_name}]
        )
        fields, parser = _version_view(summary=True)
        records = self.list_versions_raw(filters, fields, page_size=None)

        versions = [parser(record) for record in records]

        log.info(
            "sg.get_versions_for_project",
            project=project_name,
            count=len(versions),
        )
        return versions

    def _simplify_version_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a ShotGrid Version entity payload into a summary dictionary."""
        _, parser = _version_view(summary=True)
        return parser(record)

    def get_version(self, version_data: VersionData) -> Any:
        filters = self._build_version_filters(version_data)
        if not filters:
            raise ValueError("Version lookup requires at least one identifying field.")

        fields, parser = _version_view(summary=False)
        records = self.list_versions_raw(filters, fields, page_size=None)
        if not records:
            log.info("sg.version_not_found", filters=filters)
            return None

        return parser(records[0])

    def _build_version_filters(self, version_data: VersionData) -> List[Dict[str, Any]]:
        filters: List[Dict[str, Any]] = []

        if version_data.code:
            filters.append({"code": version_data.code})

        project_id = version_data.project_id or version_data.extra.get("project_id")
        if project_id:
            filters.append({"project.id[$eq]": project_id})

        project_name = version_data.extra.get("project_name") or version_data.extra.get(
            "project"
        )
        if project_name:
            filters.append({"project": project_name})

        shot_code = version_data.extra.get("shot") or version_data.extra.get(
            "shot_code"
        )
        if shot_code:
            filters.append({"entity.Shot.code[$eq]": shot_code})

        entity_relationship = version_data.extra.get("entity")
        if isinstance(entity_relationship, dict):
            entity_data = entity_relationship.get("data", entity_relationship)
            if isinstance(entity_data, dict):
                entity_type = entity_data.get("type")
                entity_id = entity_data.get("id")
                entity_code = entity_data.get("code") or entity_data.get("name")

                if entity_type and entity_id is not None:
                    filters.append({f"entity.{entity_type}.id[$eq]": entity_id})
                elif entity_id is not None:
                    filters.append({"entity.id[$eq]": entity_id})

                if entity_type and entity_code:
                    filters.append({f"entity.{entity_type}.code[$eq]": entity_code})
                elif entity_code:
                    filters.append({"entity.code[$eq]": entity_code})

        return filters

    def create_version(self, data: VersionData) -> Any:
        extra = dict(data.extra)
        entity_relationship = extra.pop("entity", None)

        attributes: Dict[str, Any] = {"code": data.code, **extra}
        if attributes.get("code") is None:
            attributes.pop("code")

        relationships: Dict[str, Any] = {}
        if data.project_id:
            relationships["project"] = {
                "data": {"type": "Project", "id": data.project_id}
            }
        if entity_relationship:
            relationships["entity"] = entity_relationship

        return self._post(data.entity_type, attributes, relationships or None)

    def update_version(
        self,
        version_id: int,
        attributes: Dict[str, Any],
        relationships: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Update an existing ShotGrid Version entity."""

        return self._patch("Version", version_id, attributes, relationships)

    def update_version_status(self, version_id: int, status: str) -> Any:
        """Convenience helper to update a version status."""

        return self.update_version(version_id, {"sg_status_list": status})

    def create_version_with_media(
        self,
        version_data: VersionData,
        media_path: Path,
    ) -> Any:
        if not media_path.exists():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        log.info(
            "sg.create_version_with_media",
            version=version_data.code,
            media=str(media_path),
        )

        version = self.create_version(version_data)

        self.upload_media(version["type"], version["id"], media_path)

        return version

    def upload_media(
        self,
        entity_type: str,
        entity_id: int,
        media_path: Path,
        upload_type: str = "sg_uploaded_movie",
    ) -> Any:
        if not media_path.exists():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        url = self._build_url(
            "api", "v1", f"entity/{entity_type.lower()}s/{entity_id}/_upload"
        )

        with media_path.open("rb") as fp:
            files = {"file": (media_path.name, fp, "application/octet-stream")}
            params = {"upload_type": upload_type}
            response = self._session.post(url, files=files, params=params)

        if not response.ok:
            log.error(
                "sg.upload_media_failed",
                entity_type=entity_type,
                entity_id=entity_id,
                media=str(media_path),
                status=response.status_code,
                text=response.text,
            )
            raise ShotGridError(
                f"Upload media failed for {entity_type} {entity_id}: {response.text}"
            )

        log.info(
            "sg.upload_media_success",
            entity_type=entity_type,
            entity_id=entity_id,
            media=str(media_path),
        )

        return response.json()

    def get_or_create_version(self, version_data: VersionData) -> Any:
        version = self.get_version(version_data)
        if version:
            return version
        return self.create_version(version_data)

    # ------------------------------------------------------------------ #
    # Tasks
    # ------------------------------------------------------------------ #
    def get_task(self, entity_id: int, task_name: TaskCode | str) -> Any:
        task_value = task_name.value if isinstance(task_name, TaskCode) else task_name
        return self._get_single(
            "Task",
            [{"entity": {"type": "Shot", "id": entity_id}}, {"content": task_value}],
            "id,content,step",
        )

    def create_task(
        self,
        data: TaskData,
        step: PipelineStep | str,
    ) -> Any:
        if not data.project_id:
            raise ValueError("Project not provided.")

        step_name = step.value if isinstance(step, PipelineStep) else step
        step_record = self._get_single(
            "Step",
            [{"code": step_name}],
            "id,code",
        )
        if not step_record:
            raise ValueError(f"Step '{step_name}' not found.")
        attributes = {**data.extra}
        if data.code:
            attributes["code"] = (
                data.code.value if isinstance(data.code, TaskCode) else data.code
            )
        relationships: Dict[str, Any] = {}
        if data.project_id:
            relationships["project"] = {
                "data": {"type": "Project", "id": data.project_id}
            }
        return self._post("Task", attributes, relationships or None)

    # ------------------------------------------------------------------ #
    # Playlists
    # ------------------------------------------------------------------ #
    def get_playlist(self, project_id: int, name: str) -> Any:
        return self._get_single(
            "Playlist", [{"project.id[$eq]": project_id}, {"code[$eq]": name}]
        )

    def create_playlist(self, data: PlaylistData) -> Any:
        relationships = {
            "project": {"data": {"type": "Project", "id": data.project_id}}
        }
        return self._post(
            data.entity_type,
            {"code": data.code, **data.extra},
            relationships,
        )
