"""Tests for the lightweight Ftrack REST client."""

from __future__ import annotations

import json
from typing import Any

import pytest

from libraries.ftrack import FtrackProject, FtrackRestClient, FtrackShot, FtrackTask


class _StubResponse:
    """Minimal response object mimicking :class:`requests.Response`."""

    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        if payload is None:
            self._content = b""
            self._json: Any = None
            self.text = ""
            self.headers = {}
        else:
            self._json = payload
            self._content = json.dumps(payload).encode("utf-8")
            self.text = self._content.decode("utf-8")
            self.headers = {"Content-Type": "application/json"}

    @property
    def content(self) -> bytes:
        return self._content

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("No JSON payload available")
        return self._json


class _StubSession:
    """Basic session stub to record outgoing requests."""

    def __init__(self, responses: dict[tuple[str, str], list[_StubResponse]]) -> None:
        self.headers: dict[str, str] = {}
        self._queues: dict[tuple[str, str], list[_StubResponse]] = {}
        for key, value in responses.items():
            method, url = key
            canonical_key = (method.upper(), url)
            self._queues.setdefault(canonical_key, []).extend(value)
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def _pop(self, method: str, url: str) -> _StubResponse:
        key = (method.upper(), url)
        queue = self._queues.get(key)
        if not queue:
            raise AssertionError(f"No stubbed response for {method} {url}")
        response = queue.pop(0)
        self._queues[key] = queue
        return response

    def post(self, url: str, json: dict[str, Any] | None = None) -> _StubResponse:
        self.requests.append(("POST", url, json))
        return self._pop("POST", url)

    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> _StubResponse:
        self.requests.append(
            (method.upper(), url, json if json is not None else params)
        )
        return self._pop(method, url)


def _make_auth_session(
    extra_responses: dict[tuple[str, str], list[_StubResponse]]
) -> _StubSession:
    base_url = "https://server"
    responses = {
        ("POST", f"{base_url}/api/authenticate"): [_StubResponse({"token": "abc123"})]
    }
    responses.update(extra_responses)
    return _StubSession(responses)


def test_authentication_sets_bearer_token() -> None:
    base_url = "https://server"
    session = _make_auth_session({})
    client = FtrackRestClient(
        base_url=base_url, api_user="user", api_key="secret", session=session
    )

    assert client.base_url == base_url
    assert session.headers["Accept"] == "application/json"
    assert session.headers["Authorization"] == "Bearer abc123"
    assert (
        "POST",
        f"{base_url}/api/authenticate",
        {"username": "user", "apiKey": "secret"},
    ) in session.requests


def test_list_projects_parses_payload_into_models() -> None:
    base_url = "https://server"
    projects_payload = {"data": [{"id": "P1", "name": "Demo"}]}
    session = _make_auth_session(
        {("GET", f"{base_url}/api/projects"): [_StubResponse(projects_payload)]}
    )
    client = FtrackRestClient(
        base_url=base_url, api_user="user", api_key="secret", session=session
    )

    projects = client.list_projects()
    assert [project.id for project in projects] == ["P1"]


def test_list_helpers_validate_required_identifiers() -> None:
    base_url = "https://server"
    session = _make_auth_session({})
    client = FtrackRestClient(
        base_url=base_url, api_user="user", api_key="secret", session=session
    )

    with pytest.raises(ValueError):
        client.list_project_shots("")
    with pytest.raises(ValueError):
        client.list_project_tasks("")


def test_workflow_stubs_raise_not_implemented() -> None:
    base_url = "https://server"
    session = _make_auth_session({})
    client = FtrackRestClient(
        base_url=base_url, api_user="user", api_key="secret", session=session
    )

    project = FtrackProject(id="P1", name="Demo")
    shot = FtrackShot(id="S1", name="sh010", project_id="P1")
    task = FtrackTask(id="T1", name="Comp", shot_id="S1")

    with pytest.raises(NotImplementedError):
        client.ensure_project(project)
    with pytest.raises(NotImplementedError):
        client.sync_shot_structure(project.id, [shot])
    with pytest.raises(NotImplementedError):
        client.sync_task_assignments(project.id, [task])
