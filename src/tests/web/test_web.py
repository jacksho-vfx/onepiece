"""Tests for the Uta web application."""

from __future__ import annotations

from typing import Any, AsyncIterator, Mapping, Sequence

from _pytest.monkeypatch import MonkeyPatch
from fastapi import Request
from fastapi.testclient import TestClient

from apps.uta import web
from apps.uta.web import RunCommandResponse

client = TestClient(web.app)


def test_run_command_failure_reports_success_flag(monkeypatch: MonkeyPatch) -> None:
    command_path = next(iter(web.COMMAND_LOOKUP))

    def fake_invoke(arguments: Sequence[str]) -> RunCommandResponse:
        assert list(arguments) == list(command_path)
        return web.RunCommandResponse(
            command=list(arguments),
            exit_code=2,
            stdout="",
            stderr="boom",
            success=False,
        )

    monkeypatch.setattr(web, "_invoke_cli", fake_invoke)

    response = client.post(
        "/api/run",
        json={"path": list(command_path), "arguments": []},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["exit_code"] == 2
    assert payload["stderr"] == "boom"


def test_run_command_accepts_structured_arguments(
    monkeypatch: MonkeyPatch,
) -> None:
    command_path = next(iter(web.COMMAND_LOOKUP))

    def fake_invoke(arguments: Sequence[str]) -> RunCommandResponse:
        assert list(arguments) == [*command_path, "--flag", "value", "--toggle"]
        return web.RunCommandResponse(
            command=list(arguments),
            exit_code=0,
            stdout="done",
            stderr="",
            success=True,
        )

    monkeypatch.setattr(web, "_invoke_cli", fake_invoke)

    response = client.post(
        "/api/run",
        json={
            "path": list(command_path),
            "arguments": ["--flag", "value", "--toggle"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["stdout"] == "done"


def test_index_renders_failure_ui_state() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    print(body)
    terms = ["render-throughput", "data-error-message"]
    for term in terms:
        assert term in body


def test_index_template_preserves_output_whitespace() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "data.stdout.trim()" not in body
    assert "data.stderr.trim()" not in body


def test_index_honours_asgi_root_path_prefix() -> None:
    command_path = next(iter(web.COMMAND_LOOKUP))
    with TestClient(web.app, root_path="/uta") as prefixed_client:
        response = prefixed_client.get("/uta/")

        assert response.status_code == 200
        body = response.text
        assert 'data-root-path="/uta"' in body
        assert 'id="uta-dashboard-chartjs"' in body
        assert 'data-dashboard-root="/uta/dashboard/"' in body

        api_response = prefixed_client.post(
            "/uta/api/run",
            json={"path": list(command_path), "arguments": []},
        )

    assert api_response.status_code == 200


def test_split_extra_args_windows_path_preserved() -> None:
    arguments = web._split_extra_args(
        "--script C:\\projects\\shot\\scene.nk", posix=False
    )

    assert arguments == ["--script", r"C:\projects\shot\scene.nk"]


def test_dashboard_refresh_bootstrap_exposes_callable() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert 'id="uta-dashboard-chartjs"' in body
    assert 'data-chart-id="render-status"' in body
    assert 'data-chart-id="render-throughput"' in body


def test_dashboard_tab_activation_triggers_refresh() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "Refresh" in body


def test_tab_query_parameter_sets_cli_section_active() -> None:
    response = client.get("/?tab=render")

    assert response.status_code == 200
    body = response.text
    assert 'class="tab-button active" data-target="page-render"' in body
    assert 'id="page-render" class="page active"' in body


def test_dashboard_query_parameter_activates_dashboard() -> None:
    response = client.get("/?tab=dashboard")

    assert response.status_code == 200
    body = response.text
    assert 'class="tab-button active" data-target="page-dashboard"' in body
    assert 'id="page-dashboard" class="page active"' in body


def test_invalid_tab_query_defaults_to_first_section() -> None:
    default_page = next(iter(web.CLI_PAGES))
    default_slug = web._slugify(default_page)

    response = client.get("/?tab=unknown")

    assert response.status_code == 200
    body = response.text
    assert f'class="tab-button active" data-target="page-{default_slug}"' in body
    assert f'id="page-{default_slug}" class="page active"' in body


def test_index_includes_pipeline_page() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert 'data-target="page-pipelines"' in body
    assert "data-pipeline-page" in body
    assert 'id="pipeline-card-template"' in body


def test_pipeline_endpoints_require_credentials() -> None:
    response = client.get("/api/pipelines")

    assert response.status_code == 401
    assert response.json()["detail"]


def test_pipeline_list_uses_client(monkeypatch: MonkeyPatch) -> None:
    class DummyClient:
        async def list_pipelines(self) -> list[dict[str, Any]]:
            return [
                {
                    "name": "demo",
                    "display_name": "Demo",
                    "description": "example",
                    "parameters": {"foo": "bar"},
                }
            ]

        async def trigger_run(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any]:  # pragma: no cover - unused
            raise AssertionError("trigger_run should not be called")

        async def get_run(
            self, *args: Any, **kwargs: Any
        ) -> dict[str, Any]:  # pragma: no cover - unused
            raise AssertionError("get_run should not be called")

        async def get_run_events(
            self, *args: Any, **kwargs: Any
        ) -> list[dict[str, Any]]:  # pragma: no cover - unused
            raise AssertionError("get_run_events should not be called")

        async def aclose(self) -> None:
            return None

    dummy = DummyClient()

    async def fake_dependency(request: Request) -> AsyncIterator[DummyClient]:
        assert isinstance(request, Request)
        yield dummy

    monkeypatch.setitem(
        web.app.dependency_overrides, web.get_pipeline_client, fake_dependency
    )

    response = client.get(
        "/api/pipelines",
        headers={"Authorization": "Bearer demo-token"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["name"] == "demo"


def test_pipeline_run_proxy(monkeypatch: MonkeyPatch) -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.triggered: dict[str, Any] | None = None

        async def list_pipelines(
            self,
        ) -> list[dict[str, Any]]:  # pragma: no cover - unused
            raise AssertionError("list_pipelines should not be called")

        async def trigger_run(
            self, pipeline: str, *, parameters: Mapping[str, Any] | None = None
        ) -> dict[str, Any]:
            self.triggered = {
                "pipeline": pipeline,
                "parameters": dict(parameters or {}),
            }
            return {
                "id": "run-1",
                "pipeline": pipeline,
                "status": "queued",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "parameters": dict(parameters or {}),
            }

        async def get_run(self, run_id: str) -> dict[str, Any]:
            return {
                "id": run_id,
                "pipeline": "demo",
                "status": "succeeded",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:05Z",
                "parameters": {"foo": "bar"},
            }

        async def get_run_events(self, run_id: str) -> list[dict[str, Any]]:
            return [
                {
                    "id": run_id,
                    "pipeline": "demo",
                    "status": "queued",
                    "timestamp": "2024-01-01T00:00:00Z",
                    "parameters": {"foo": "bar"},
                }
            ]

        async def aclose(self) -> None:
            return None

    client_stub = RecordingClient()

    async def fake_dependency(request: Request) -> AsyncIterator[RecordingClient]:
        assert isinstance(request, Request)
        yield client_stub

    monkeypatch.setitem(
        web.app.dependency_overrides, web.get_pipeline_client, fake_dependency
    )

    run_response = client.post(
        "/api/pipelines/demo/runs",
        json={"parameters": {"foo": "baz"}},
        headers={"Authorization": "Bearer demo-token"},
    )

    assert run_response.status_code == 201
    assert client_stub.triggered == {
        "pipeline": "demo",
        "parameters": {"foo": "baz"},
    }

    detail_response = client.get(
        "/api/pipelines/runs/run-1",
        headers={"Authorization": "Bearer demo-token"},
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "succeeded"

    events_response = client.get(
        "/api/pipelines/runs/run-1/events",
        headers={"Authorization": "Bearer demo-token"},
    )
    assert events_response.status_code == 200
    events = events_response.json()
    assert events[0]["status"] == "queued"
