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
    assert "status.textContent = 'Failed';" in body
    assert "status.classList.add('status-error');" in body


def test_index_template_preserves_output_whitespace() -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "data.stdout.trim()" not in body
    assert "data.stderr.trim()" not in body
    assert "const trailingNewlinePattern = /\\r?\\n$/;" in body
    assert "cleaned.length > 0 ? cleaned : null;" in body
