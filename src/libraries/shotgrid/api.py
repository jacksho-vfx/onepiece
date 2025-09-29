"""ShotGrid API client helpers used by the legacy library layer."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from upath import UPath
import requests
import structlog

from libraries.shotgrid.config import load_config
from libraries.shotgrid.models import (
    EpisodeData,
    PlaylistData,
    SceneData,
    ShotData,
    VersionData,
)

from libraries.shotgrid.models import PipelineStep, TaskCode, TaskData

log = structlog.get_logger(__name__)


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
        self.base_url = UPath(base_url or cfg.base_url)
        script_name = script_name or cfg.script_name
        api_key = api_key or cfg.api_key

        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._authenticate(script_name, api_key)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _authenticate(self, script_name: str, api_key: str) -> None:
        url = self.base_url / "api" / "v1" / "auth" / "access_token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": script_name,
            "client_secret": api_key,
        }
        r = self._session.post(str(url), json=payload)
        if not r.ok:
            log.error("auth_failed", status=r.status_code, text=r.text)
            raise ShotGridError(f"Authentication failed: {r.status_code}")
        token = r.json()["access_token"]
        self._session.headers.update({"Authorization": f"Bearer {token}"})
        log.info("auth_success", base_url=str(self.base_url))

    def _get(self, entity: str, filters: List[Dict[str, Any]], fields: str) -> Any:
        url = self.base_url / "api" / "v1" / f"entities/{entity.lower()}s"
        params: Dict[str, Any] = {"fields": fields}
        for idx, f in enumerate(filters):
            for key, value in f.items():
                params[f"filter[{idx}][{key}]"] = value
        r = self._session.get(str(url), params=params)
        if not r.ok:
            log.error(
                "http_get_failed", entity=entity, status=r.status_code, text=r.text
            )
            raise ShotGridError(f"GET {entity} failed: {r.text}")
        return r.json().get("data", [])

    def _post(
        self,
        entity: str,
        attributes: Dict[str, Any],
        relationships: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = self.base_url / "api" / "v1" / f"entities/{entity.lower()}s"
        payload: Dict[str, Any] = {"data": {"type": entity, "attributes": attributes}}
        if relationships:
            payload["data"]["relationships"] = relationships
        r = self._session.post(str(url), json=payload)
        if not r.ok:
            log.error(
                "http_post_failed", entity=entity, status=r.status_code, text=r.text
            )
            raise ShotGridError(f"POST {entity} failed: {r.text}")
        return r.json()["data"]

    def _get_single(
        self, entity: str, filters: List[Dict[str, Any]], fields: str = "id,name,code"
    ) -> Optional[Dict[str, Any]]:
        results = self._get(entity, filters, fields)
        return results[0] if results else None

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
        project = self.get_project(name)
        if project:
            return project
        return self.create_project(name, template)

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
        if not data.code or not data.project_id:
            episode = None
        else:
            episode = self.get_episode(data.project_id, data.code)
        if episode:
            return episode
        return self.create_episode(data)

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
        if not data.code or not data.project_id:
            scene = None
        else:
            scene = self.get_scene(data.project_id, data.code)
        if scene:
            return scene
        return self.create_scene(data)

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
        if not data.code or not data.project_id:
            shot = None
        else:
            shot = self.get_shot(data.project_id, data.code)
        if shot:
            return shot
        return self.create_shot(data)

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
        fields = ",".join(
            [
                "code",
                "version_number",
                "sg_status_list",
                "sg_path_to_movie",
                "sg_uploaded_movie",
                "entity",
            ]
        )
        records = self._get("Version", filters, fields)

        versions: List[Dict[str, Any]] = []
        for record in records:
            attributes = record.get("attributes", {})
            relationships = record.get("relationships", {})
            entity_data = relationships.get("entity", {}).get("data", {})
            shot_name = (
                entity_data.get("name")
                or entity_data.get("code")
                or attributes.get("code")
            )
            versions.append(
                {
                    "shot": shot_name,
                    "version_number": attributes.get("version_number"),
                    "file_path": attributes.get("sg_path_to_movie")
                    or attributes.get("sg_uploaded_movie"),
                    "status": attributes.get("sg_status_list"),
                    "code": attributes.get("code"),
                }
            )

        log.info(
            "sg.get_versions_for_project",
            project=project_name,
            count=len(versions),
        )
        return versions

    def get_version(self, version_data: VersionData) -> Any:
        return self.get_version(version_data)

    def create_version(self, data: VersionData) -> Any:
        attributes = {"code": data.code, **data.extra}
        relationships: Dict[str, Any] = {}
        if data.project_id:
            relationships["project"] = {
                "data": {"type": "Project", "id": data.project_id}
            }
        return self._post(data.entity_type, attributes, relationships or None)

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

        url = (
            self.base_url
            / "api"
            / "v1"
            / f"entity/{entity_type.lower()}s/{entity_id}/_upload"
        )

        with media_path.open("rb") as fp:
            files = {"file": (media_path.name, fp, "application/octet-stream")}
            params = {"upload_type": upload_type}
            response = self._session.post(str(url), files=files, params=params)

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
