"""Tests for the Uta web application."""

from __future__ import annotations

from typing import Sequence

from _pytest.monkeypatch import MonkeyPatch
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
        json={"path": list(command_path), "extra_args": ""},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["exit_code"] == 2
    assert payload["stderr"] == "boom"


def test_index_renders_failure_ui_state() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "status.textContent = 'Request error';" in body
    assert "status.textContent = `Failed (exit code ${data.exit_code})`;" in body


def test_index_template_preserves_output_whitespace() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "data.stdout.trim()" not in body
    assert "data.stderr.trim()" not in body
    assert "const cleaned = value.replace(trailingNewlinePattern, '');" in body
    assert "cleaned.length > 0 ? cleaned : null;" in body


def test_index_honours_asgi_root_path_prefix() -> None:
    command_path = next(iter(web.COMMAND_LOOKUP))
    with TestClient(web.app, root_path="/uta") as prefixed_client:
        response = prefixed_client.get("/uta/")

        assert response.status_code == 200
        body = response.text
        assert 'data-root-path="/uta"' in body
        assert 'id="uta-dashboard-chartjs"' in body
        assert 'data-dashboard-root="/uta/dashboard/"' in body
        assert "const rootPath = document.body.dataset.rootPath" in body
        assert "fetch(joinWithRoot('/api/run')" in body

        api_response = prefixed_client.post(
            "/uta/api/run",
            json={"path": list(command_path), "extra_args": ""},
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
    assert "window.triggerDashboardRefresh = () => {};" in body
    assert "chartScript.addEventListener('load', markReady" in body


def test_dashboard_tab_activation_triggers_refresh() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert (
        "targetId === 'page-dashboard' && typeof window.triggerDashboardRefresh === 'function'"
        in body
    )
    assert "window.triggerDashboardRefresh();" in body
