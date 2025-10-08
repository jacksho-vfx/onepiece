"""Tests for the Uta web application."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.uta import web


client = TestClient(web.app)


def test_run_command_failure_reports_success_flag(monkeypatch):
    command_path = next(iter(web.COMMAND_LOOKUP))

    def fake_invoke(arguments):
        # The endpoint should pass the command path through unchanged when no extra args are provided.
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


def test_index_renders_failure_ui_state():
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "status.textContent = 'Failed';" in body
    assert "status.classList.add('status-error');" in body

