"""Mudstack API client helpers inspired by the ShotGrid integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import requests
import structlog

from libraries.integrations.mudstack.config import load_config
from libraries.integrations.mudstack.models import (
    AssetData,
    MudstackEntity,
    ProjectData,
    ReviewSessionData,
    TaskData,
)

log = structlog.get_logger(__name__)


class MudstackError(Exception):
    """Raised when Mudstack operations fail."""


class MudstackClient:
    """Thin REST client for Mudstack production tracking APIs."""

    DEFAULT_TIMEOUT: float = 10.0

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        workspace: str | None = None,
        timeout: float | tuple[float, float] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        cfg = None
        if base_url is None or api_key is None:
            cfg = load_config()

        resolved_base_url = base_url or (cfg.base_url if cfg else None)
        resolved_workspace = (
            workspace if workspace is not None else (cfg.workspace if cfg else None)
        )
        api_key_value = api_key or (cfg.api_key if cfg else None)

        if resolved_base_url is None or api_key_value is None:
            raise MudstackError(
                "Missing Mudstack configuration. Provide base_url and api_key."
            )

        self.base_url: str = resolved_base_url
        self.workspace: str | None = resolved_workspace

        self.timeout: float | tuple[float, float]
        if timeout is not None:
            self.timeout = timeout
        else:
            self.timeout = self.DEFAULT_TIMEOUT

        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Authorization": f"Bearer {api_key_value}",
            }
        )
        if self.workspace:
            self._session.headers.update({"X-Mudstack-Workspace": self.workspace})

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _build_url(self, *segments: str) -> str:
        base = self.base_url.rstrip("/")
        path = "/".join(part.strip("/") for part in segments if part)
        return f"{base}/{path}" if path else base

    def _extract_data(self, payload: Any) -> Any:
        if isinstance(payload, Mapping) and "data" in payload:
            return payload["data"]
        return payload

    def _extract_mapping(self, payload: Any) -> dict[str, Any]:
        extracted = self._extract_data(payload)
        if isinstance(extracted, Mapping):
            return dict(extracted)

        raise MudstackError("Mudstack response payload was not a mapping")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = self._build_url(path)
        response = self._session.request(
            method=method, url=url, timeout=self.timeout, **kwargs
        )
        if not response.ok:
            log.error(
                "mudstack.request_failed",
                method=method,
                url=url,
                status=response.status_code,
                text=response.text,
            )
            raise MudstackError(
                f"{method.upper()} {url} failed: {response.status_code}"
            )

        try:
            return response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            raise MudstackError("Failed to decode Mudstack response JSON") from exc

    # ------------------------------------------------------------------ #
    # Projects
    # ------------------------------------------------------------------ #
    def list_projects(self) -> list[dict[str, Any]]:
        payload = self._request("get", "api/v1/projects")
        return list(self._extract_data(payload) or [])

    def create_project(self, data: ProjectData) -> dict[str, Any]:
        payload = self._request("post", "api/v1/projects", json=data.to_payload())
        return self._extract_mapping(payload)

    def get_project(self, project_id: str) -> dict[str, Any]:
        payload = self._request("get", f"api/v1/projects/{project_id}")
        return self._extract_mapping(payload)

    # ------------------------------------------------------------------ #
    # Generic helpers
    # ------------------------------------------------------------------ #
    def create_entity(self, data: MudstackEntity) -> dict[str, Any]:
        payload = self._request(
            "post", f"api/v1/{data.resource}", json=data.to_payload()
        )
        return self._extract_mapping(payload)

    def update_entity(
        self, resource: str, entity_id: str, updates: MutableMapping[str, Any]
    ) -> dict[str, Any]:
        payload = self._request(
            "patch",
            f"api/v1/{resource}/{entity_id}",
            json={"metadata": dict(updates)},
        )
        return self._extract_mapping(payload)

    def list_entities(
        self, resource: str, *, filters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        payload = self._request("get", f"api/v1/{resource}", params=filters)
        return list(self._extract_data(payload) or [])

    # ------------------------------------------------------------------ #
    # Assets & tasks
    # ------------------------------------------------------------------ #
    def create_asset(self, data: AssetData) -> dict[str, Any]:
        return self.create_entity(data)

    def create_task(self, data: TaskData) -> dict[str, Any]:
        return self.create_entity(data)

    def update_task_status(self, task_id: str, status: str) -> dict[str, Any]:
        return self.update_entity("tasks", task_id, {"status": status})

    # ------------------------------------------------------------------ #
    # Reviews
    # ------------------------------------------------------------------ #
    def create_review_session(self, data: ReviewSessionData) -> dict[str, Any]:
        return self.create_entity(data)

    def attach_versions_to_review(
        self, review_id: str, version_ids: Sequence[str]
    ) -> dict[str, Any]:
        payload = {
            "version_ids": list(version_ids),
        }
        response = self._request(
            "post", f"api/v1/reviews/{review_id}/versions", json=payload
        )
        return self._extract_mapping(response)

    # ------------------------------------------------------------------ #
    # Media
    # ------------------------------------------------------------------ #
    def upload_media(
        self, resource: str, entity_id: str, media_path: Path, *, field: str = "media"
    ) -> dict[str, Any]:
        if not media_path.exists():
            raise FileNotFoundError(f"Media file not found: {media_path}")

        with media_path.open("rb") as handle:
            files = {field: (media_path.name, handle, "application/octet-stream")}
            payload = self._request(
                "post",
                f"api/v1/{resource}/{entity_id}/upload",
                files=files,
            )
        return self._extract_mapping(payload)

    # ------------------------------------------------------------------ #
    # Factories
    # ------------------------------------------------------------------ #
    @classmethod
    def from_environment(cls) -> "MudstackClient":
        cfg = load_config()
        return cls(base_url=cfg.base_url, api_key=cfg.api_key, workspace=cfg.workspace)

    @classmethod
    def from_api_key(
        cls, base_url: str, api_key: str, *, workspace: str | None = None
    ) -> "MudstackClient":
        return cls(base_url=base_url, api_key=api_key, workspace=workspace)


__all__ = ["MudstackClient", "MudstackError"]
