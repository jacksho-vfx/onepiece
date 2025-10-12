"""Thin REST client tailored for the Ftrack API.

The module exposes :class:`FtrackRestClient` which provides typed helpers for
listing and retrieving common entities such as projects, shots, and tasks.
"""

from __future__ import annotations

import structlog

from typing import Any, Sequence
from urllib.parse import urljoin

import requests
from requests import Session

from .models import FtrackProject, FtrackShot, FtrackTask

log = structlog.getLogger(__name__)


class FtrackError(RuntimeError):
    """Raised when communication with the Ftrack API fails."""


class FtrackRestClient:
    """Helper for interacting with the Ftrack REST API."""

    def __init__(
        self,
        base_url: str,
        api_user: str,
        api_key: str,
        *,
        session: Session | None = None,
        auto_authenticate: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be provided")
        if not api_user:
            raise ValueError("api_user must be provided")
        if not api_key:
            raise ValueError("api_key must be provided")

        self.base_url = base_url.rstrip("/")
        self.api_user = api_user
        self.api_key = api_key
        self._session = session or requests.Session()
        self._session.headers.setdefault("Accept", "application/json")

        if auto_authenticate:
            self._authenticate()

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _authenticate(self) -> None:
        """Authenticate against Ftrack and persist a bearer token."""

        url = self._build_url("api", "authenticate")
        payload = {"username": self.api_user, "apiKey": self.api_key}
        log.debug("ftrack.authenticate", url=url)
        response = self._session.post(url, json=payload)
        if not response.ok:
            log.error(
                "ftrack.auth_failed", status=response.status_code, text=response.text
            )
            raise FtrackError("Authentication failed")

        data = response.json() if response.content else {}
        token = data.get("token") or data.get("access_token")
        if not token:
            log.error("ftrack.auth_missing_token", payload=data)
            raise FtrackError("Authentication response did not contain a token")

        self._session.headers["Authorization"] = f"Bearer {token}"
        log.info("ftrack.authenticated", base_url=self.base_url)

    def _build_url(self, *segments: str) -> str:
        base = f"{self.base_url}/"
        path = "/".join(segment.strip("/") for segment in segments if segment)
        return urljoin(base, path)

    def _request(
        self,
        method: str,
        *segments: str,
        params: dict[str, Any] | None = None,
        payload: Any | None = None,
    ) -> Any:
        url = self._build_url(*segments)
        log.debug("ftrack.request", method=method, url=url, params=params)
        response = self._session.request(method, url, params=params, json=payload)
        if not response.ok:
            log.error(
                "ftrack.request_failed",
                method=method,
                url=url,
                status=response.status_code,
                text=response.text,
            )
            raise FtrackError(f"HTTP {method} {url} failed with {response.status_code}")

        if not response.content:
            return None

        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type:
            return response.json()
        return response.text

    def _get(self, *segments: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", *segments, params=params)

    def _post(
        self,
        *segments: str,
        payload: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._request("POST", *segments, params=params, payload=payload)

    # ------------------------------------------------------------------
    # Entity helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_items(payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("data", "items", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        raise FtrackError("Unexpected payload structure returned by the API")

    @staticmethod
    def _extract_item(payload: Any) -> dict[str, Any] | None:
        if payload is None:
            return None
        if isinstance(payload, dict):
            for key in ("data", "item", "result"):
                value = payload.get(key)
                if isinstance(value, list):
                    if not value:
                        return None
                    first = value[0]
                    if not isinstance(first, dict):
                        break
                    return first
                if isinstance(value, dict):
                    return value
            if "id" in payload:
                return payload
        if isinstance(payload, list):
            if not payload:
                return None
            first = payload[0]
            if isinstance(first, dict):
                return first
        raise FtrackError("Unexpected payload structure returned by the API")

    def list_projects(self) -> list[FtrackProject]:
        """Return all projects visible to the API user."""

        payload = self._get("api", "projects")
        return [
            FtrackProject.model_validate(item) for item in self._extract_items(payload)
        ]

    def list_project_shots(self, project_id: str) -> list[FtrackShot]:
        """Return the shots for a project."""

        if not project_id:
            raise ValueError("project_id must be provided")
        payload = self._get("api", "projects", project_id, "shots")
        return [
            FtrackShot.model_validate(item) for item in self._extract_items(payload)
        ]

    def list_project_tasks(self, project_id: str) -> list[FtrackTask]:
        """Return all tasks for a project."""

        if not project_id:
            raise ValueError("project_id must be provided")
        payload = self._get("api", "projects", project_id, "tasks")
        return [
            FtrackTask.model_validate(item) for item in self._extract_items(payload)
        ]

    def get_project(self, project_id: str) -> FtrackProject | None:
        """Return a single project if it exists."""

        if not project_id:
            raise ValueError("project_id must be provided")
        payload = self._get(
            "api", "projects", params={"filter": f"id={project_id}"}
        )
        item = self._extract_item(payload)
        if item is None:
            return None
        return FtrackProject.model_validate(item)

    def get_shot(self, shot_id: str) -> FtrackShot | None:
        """Return a single shot if it exists."""

        if not shot_id:
            raise ValueError("shot_id must be provided")
        payload = self._get("api", "shots", params={"filter": f"id={shot_id}"})
        item = self._extract_item(payload)
        if item is None:
            return None
        return FtrackShot.model_validate(item)

    def get_task(self, task_id: str) -> FtrackTask | None:
        """Return a single task if it exists."""

        if not task_id:
            raise ValueError("task_id must be provided")
        payload = self._get("api", "tasks", params={"filter": f"id={task_id}"})
        item = self._extract_item(payload)
        if item is None:
            return None
        return FtrackTask.model_validate(item)

    # ------------------------------------------------------------------
    # Workflow stubs
    # ------------------------------------------------------------------
    def ensure_project(self, project: FtrackProject) -> FtrackProject:
        """Ensure a project exists, creating or updating it as required."""

        raise NotImplementedError(
            "Project reconciliation has not been implemented yet."
        )

    def sync_shot_structure(
        self, project_id: str, shots: Sequence[FtrackShot]
    ) -> list[FtrackShot]:
        """Synchronise the given shots with the remote project structure."""

        raise NotImplementedError("Shot synchronisation is not yet implemented.")

    def sync_task_assignments(
        self, project_id: str, tasks: Sequence[FtrackTask]
    ) -> list[FtrackTask]:
        """Synchronise task assignments and statuses for the given project."""

        raise NotImplementedError(
            "Task assignment synchronisation is pending implementation."
        )
