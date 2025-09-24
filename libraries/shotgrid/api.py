"""ShotGrid API client helpers used by the legacy library layer."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import UPath
import requests
import structlog

from libraries.shotgrid.config import load_config
from libraries.shotgrid.models import (
    EpisodeData,
    PlaylistData,
    ProjectData,
    SceneData,
    ShotData,
    VersionData,
)

log = structlog.get_logger(__name__)


class ShotGridError(Exception):
    """Raised when ShotGrid operations fail."""


class ShotGridClient:
    """REST client for Autodesk ShotGrid using xData models for create."""

    def __init__(self, base_url: Optional[str] = None,
                 script_name: Optional[str] = None,
                 api_key: Optional[str] = None) -> None:
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

    def _get(self, entity: str,
             filters: List[Dict[str, Any]],
             fields: str) -> List[Dict[str, Any]]:
        url = self.base_url / "api" / "v1" / f"entities/{entity.lower()}s"
        params: Dict[str, Any] = {"fields": fields}
        for idx, f in enumerate(filters):
            for key, value in f.items():
                params[f"filter[{idx}][{key}]"] = value
        r = self._session.get(str(url), params=params)
        if not r.ok:
            log.error("http_get_failed", entity=entity, status=r.status_code, text=r.text)
            raise ShotGridError(f"GET {entity} failed: {r.text}")
        return r.json().get("data", [])

    def _post(self, entity: str,
              attributes: Dict[str, Any],
              relationships: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = self.base_url / "api" / "v1" / f"entities/{entity.lower()}s"
        payload: Dict[str, Any] = {"data": {"type": entity, "attributes": attributes}}
        if relationships:
            payload["data"]["relationships"] = relationships
        r = self._session.post(str(url), json=payload)
        if not r.ok:
            log.error("http_post_failed", entity=entity, status=r.status_code, text=r.text)
            raise ShotGridError(f"POST {entity} failed: {r.text}")
        return r.json()["data"]

    def _get_single(self, entity: str,
                    filters: List[Dict[str, Any]],
                    fields: str = "id,name,code") -> Optional[Dict[str, Any]]:
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
    def get_project(self, name: str, template: str | None) -> Optional[Dict[str, Any]]:
        return self._get_single("Project", [{"name": name}, {"template": template}])

    def get_project_id_by_name(self, project_name: str) -> Optional[int]:
        log.debug("sg.get_project_id_by_name", project=project_name)
        filters = [["name", "is", project_name]]
        fields = ["id"]
        result = self.sg.find_one("Project", filters, fields)
        return result["id"] if result else None

    def create_project(self, data: ProjectData) -> Dict[str, Any]:
        return self._post(
            data.entity_type,
            {"name": data.name, "code": data.code, **data.extra}
        )
        
    def get_or_create_project(self, name: str, template: str) -> dict:
        project = self.get_project_by_name(name)
        if project:
            return project
        return self.create_project(name, template)

    # ------------------------------------------------------------------ #
    # Episodes
    # ------------------------------------------------------------------ #
    def get_episode(self, project_id: int, name: str) -> Optional[Dict[str, Any]]:
        return self._get_single(
            "Episode", [{"project.id[$eq]": project_id}, {"code[$eq]": name}]
        )

    def create_episode(self, data: EpisodeData) -> Dict[str, Any]:
        return self._post(
            data.entity_type,
            {"code": data.code, **data.extra},
            {"project": {"data": {"type": "Project", "id": data.project_id}}},
        )
        
    def get_or_create_episode(self, project_id: int, name: str) -> Dict[str, Any]:
        episode = self.get_episode(project_id, name)
        if episode:
            return episode
        return self.create_episode(project_id, name)

    # ------------------------------------------------------------------ #
    # Scenes
    # ------------------------------------------------------------------ #
    def get_scene(self, project_id: int, name: str) -> Optional[Dict[str, Any]]:
        return self._get_single(
            "Scene", [{"project.id[$eq]": project_id}, {"code[$eq]": name}]
        )

    def create_scene(self, data: SceneData) -> Dict[str, Any]:
        return self._post(
            data.entity_type,
            {"code": data.code, **data.extra},
            {"project": {"data": {"type": "Project", "id": data.project_id}}},
        )
        
    def get_or_create_scene(self, project_id: int, data: SceneData) -> Dict[str, Any]:
        scene = self.get_scene(project_id, data.name)
        if scene:
            return scene
        return self.create_scene(project_id, data)

    # ------------------------------------------------------------------ #
    # Shots
    # ------------------------------------------------------------------ #
    def get_shot(self, project_name: str, shot_name: str) -> Optional[Dict[str, Any]]:
        pid = self.get_project_id_by_name(project_name)
        if not pid:
            log.warning("project_not_found", project=project_name)
            return None
        filters = [
            ["project", "is", {"type": "Project", "id": pid}],
            ["code", "is", shot_name],
        ]
        fields = ["id", "code", "sg_status_list"]
        return self.sg.find_one("Shot", filters, fields)

    def create_shot(self, data: ShotData) -> Dict[str, Any]:
        rel = {"project": {"data": {"type": "Project", "id": data.project_id}}}
        if data.scene_id:
            rel["scene"] = {"data": {"type": "Scene", "id": data.scene_id}}
        return self._post(data.entity_type, {"code": data.code, **data.extra}, rel)
        
    def get_or_create_shot(self, project_id: int, shot_name: str) -> dict:
        shot = self.get_shot(project_id, shot_name)
        if shot:
            return shot
        return self.create_shot(project_id, shot_name)

    # ------------------------------------------------------------------ #
    # Versions
    # ------------------------------------------------------------------ #
    def get_version(self, version_data: VersionData) -> Optional[Dict[str, Any]]:
        return self.sg.get("Version", version_data)

    def create_version(self, data: VersionData) -> Dict[str, Any]:
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
    ) -> Dict[str, Any]:
        if not media_path.exists():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        log.info(
            "sg.create_version_with_media",
            version=version_data.code,
            media=str(media_path),
        )

        version = self.create_version(version_data)

        self.sg.upload(
            entity_type="Version",
            entity_id=version["id"],
            path=str(media_path),
            field_name="sg_uploaded_movie",
        )
        return version
        
    def get_or_create_version(self, version_data: VersionData) -> Dict[str, Any]:
        version = self.get_version(version_data)
        if version:
            return version
        return self.create_version(version_data)

    # ------------------------------------------------------------------ #
    # Tasks
    # ------------------------------------------------------------------ #
    def get_task(self, entity_id: int, task_name: str) -> Optional[Dict[str, Any]]:
        filters = [
            ["entity", "is", {"type": "Shot", "id": entity_id}],
            ["content", "is", task_name],
        ]
        fields = ["id", "content", "step"]
        return self.sg.find_one("Task", filters, fields)

    def create_task(
        self,
        project_name: str,
        entity_type: str,
        entity_id: int,
        name: str,
        step_name: str,
    ) -> Dict[str, Any]:
        pid = self.get_project_id_by_name(project_name)
        if not pid:
            raise ValueError(f"Project '{project_name}' not found.")

        step = self.sg.find_one(
            "Step",
            [["code", "is", step_name]],
            ["id", "code"],
        )
        if not step:
            raise ValueError(f"Step '{step_name}' not found.")

        data = {
            "project": {"type": "Project", "id": pid},
            "entity": {"type": entity_type, "id": entity_id},
            "content": name,
            "step": {"type": "Step", "id": step["id"]},
        }
        return self.sg.create("Task", data)

    # ------------------------------------------------------------------ #
    # Playlists
    # ------------------------------------------------------------------ #
    def get_playlist(self, project_id: int, name: str) -> Optional[Dict[str, Any]]:
        return self._get_single(
            "Playlist", [{"project.id[$eq]": project_id}, {"code[$eq]": name}]
        )

    def create_playlist(self, data: PlaylistData) -> Dict[str, Any]:
        relationships = {
            "project": {"data": {"type": "Project", "id": data.project_id}}
        }
        if data.version_ids:
            relationships["versions"] = {
                "data": [{"type": "Version", "id": vid} for vid in data.version_ids]
            }
        return self._post(
            data.entity_type,
            {"code": data.code, **data.extra},
            relationships,
        )
