"""Tests for the lightweight Ftrack REST client."""

from __future__ import annotations

import json
from typing import Any

import pytest

from libraries.integrations.ftrack import (
    FtrackCredentials,
    FtrackError,
    FtrackProject,
    FtrackRestClient,
    FtrackShot,
    FtrackTask,
    load_credentials,
)


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
    extra_responses: dict[tuple[str, str], list[_StubResponse]],
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


def test_client_accepts_existing_bearer_token() -> None:
    base_url = "https://server"
    session = _StubSession({})

    client = FtrackRestClient(
        base_url=base_url, bearer_token="existing", session=session
    )

    assert client.base_url == base_url
    assert session.headers["Accept"] == "application/json"
    assert session.headers["Authorization"] == "Bearer existing"
    assert session.requests == []


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
    with pytest.raises(ValueError):
        client.get_project("")
    with pytest.raises(ValueError):
        client.get_shot("")
    with pytest.raises(ValueError):
        client.get_task("")

    with pytest.raises(ValueError):
        FtrackRestClient(base_url=base_url, api_user="", api_key="secret")


@pytest.mark.parametrize(
    (
        "method_name",
        "identifier",
        "endpoint",
        "payload",
        "expected_type",
    ),
    [
        (
            "get_project",
            "P1",
            "api/projects",
            {"data": [{"id": "P1", "name": "Demo"}]},
            FtrackProject,
        ),
        (
            "get_shot",
            "S1",
            "api/shots",
            {"data": [{"id": "S1", "name": "sh010", "project_id": "P1"}]},
            FtrackShot,
        ),
        (
            "get_task",
            "T1",
            "api/tasks",
            {"data": [{"id": "T1", "name": "Comp"}]},
            FtrackTask,
        ),
    ],
)
def test_get_helpers_return_models(
    method_name: str,
    identifier: str,
    endpoint: str,
    payload: dict[str, Any],
    expected_type: type[Any],
) -> None:
    base_url = "https://server"
    session = _make_auth_session(
        {("GET", f"{base_url}/{endpoint}"): [_StubResponse(payload)]}
    )
    client = FtrackRestClient(
        base_url=base_url, api_user="user", api_key="secret", session=session
    )

    method = getattr(client, method_name)
    result = method(identifier)

    assert isinstance(result, expected_type)
    assert result and result.id == identifier
    assert (
        "GET",
        f"{base_url}/{endpoint}",
        {"filter": f"id={identifier}"},
    ) in session.requests


@pytest.mark.parametrize(
    ("method_name", "identifier", "endpoint"),
    [
        ("get_project", "P1", "api/projects"),
        ("get_shot", "S1", "api/shots"),
        ("get_task", "T1", "api/tasks"),
    ],
)
def test_get_helpers_return_none_when_not_found(
    method_name: str, identifier: str, endpoint: str
) -> None:
    base_url = "https://server"
    session = _make_auth_session(
        {("GET", f"{base_url}/{endpoint}"): [_StubResponse({"data": []})]}
    )
    client = FtrackRestClient(
        base_url=base_url, api_user="user", api_key="secret", session=session
    )

    method = getattr(client, method_name)
    assert method(identifier) is None


@pytest.mark.parametrize(
    ("method_name", "identifier", "endpoint"),
    [
        ("get_project", "P1", "api/projects"),
        ("get_shot", "S1", "api/shots"),
        ("get_task", "T1", "api/tasks"),
    ],
)
def test_get_helpers_validate_payload_shape(
    method_name: str, identifier: str, endpoint: str
) -> None:
    base_url = "https://server"
    invalid_payload = {"data": ["unexpected"]}
    session = _make_auth_session(
        {("GET", f"{base_url}/{endpoint}"): [_StubResponse(invalid_payload)]}
    )
    client = FtrackRestClient(
        base_url=base_url, api_user="user", api_key="secret", session=session
    )

    method = getattr(client, method_name)
    with pytest.raises(FtrackError):
        method(identifier)


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


def test_client_from_credentials_uses_bearer_token() -> None:
    credentials = FtrackCredentials(base_url="https://server", bearer_token="token")
    session = _StubSession({})

    client = FtrackRestClient.from_credentials(credentials, session=session)

    assert client.base_url == "https://server"
    assert session.headers["Authorization"] == "Bearer token"
    assert session.requests == []


def test_load_credentials_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FTRACK_URL", "https://env")
    monkeypatch.setenv("FTRACK_API_USER", "env_user")
    monkeypatch.setenv("FTRACK_API_KEY", "env_key")

    credentials = load_credentials()

    assert credentials.base_url == "https://env"
    assert credentials.api_user == "env_user"
    assert credentials.api_key == "env_key"


def test_load_credentials_merges_file_and_env(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "base_url": "https://file",
        "api_user": "file_user",
        "api_key": "file_key",
    }
    credentials_file = tmp_path / "ftrack.json"
    credentials_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("FTRACK_CREDENTIALS_FILE", str(credentials_file))
    monkeypatch.setenv("FTRACK_URL", "https://env")
    monkeypatch.setenv("FTRACK_BEARER_TOKEN", "token")

    credentials = load_credentials()

    assert credentials.base_url == "https://env"
    assert credentials.api_user == "file_user"
    assert credentials.api_key == "file_key"
    assert credentials.bearer_token == "token"


def test_load_credentials_requires_auth_inputs(tmp_path: Any) -> None:
    credentials_file = tmp_path / "ftrack.json"
    credentials_file.write_text(
        json.dumps({"base_url": "https://file"}), encoding="utf-8"
    )

    with pytest.raises(ValueError):
        load_credentials(credentials_file)
