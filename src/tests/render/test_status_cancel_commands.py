"""Tests for render status and cancel CLI commands."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app
from apps.onepiece.render import submit as submit_module
from apps.onepiece.utils.errors import OnePieceExternalServiceError


class _StubRenderClient:
    """Test double mimicking ``RenderJobClient`` for status lookups."""

    def __init__(
        self,
        *,
        profile: str | None = None,
        response: Any = None,
        error: Exception | None = None,
        cancel_response: Any = None,
        cancel_error: Exception | None = None,
    ) -> None:
        self.profile = profile
        self.response = response
        self.error = error
        self.cancel_response = cancel_response
        self.cancel_error = cancel_error
        self.closed = False
        self.calls: list[tuple[str, str | None]] = []
        self.cancel_calls: list[str] = []

    def __enter__(self) -> "_StubRenderClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def get_job(self, job_id: str, farm: str | None = None) -> Any:
        self.calls.append((job_id, farm))
        if self.error:
            raise self.error
        return self.response

    def cancel_job(self, job_id: str) -> Any:
        self.cancel_calls.append(job_id)
        if self.cancel_error:
            raise self.cancel_error
        return self.cancel_response


def test_render_status_success(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    payload = {
        "job_id": "job-42",
        "farm": "mock",
        "farm_type": "mock",
        "status": "running",
        "message": "Frame 5 of 10",
        "status_history": [
            {"status": "queued", "timestamp": "2024-05-01T10:00:00Z"},
            {"status": "running", "timestamp": "2024-05-01T10:05:00Z"},
        ],
    }

    stub = _StubRenderClient(response=payload)
    monkeypatch.setattr(submit_module, "RenderJobClient", lambda **kwargs: stub)

    result = runner.invoke(app, ["render", "status", "job-42"])

    assert result.exit_code == 0, result.stdout
    assert "Status: running" in result.stdout
    assert "Message: Frame 5 of 10" in result.stdout
    assert "History:" in result.stdout
    assert "queued at 2024-05-01T10:00:00Z" in result.stdout
    assert "running at 2024-05-01T10:05:00Z" in result.stdout
    assert stub.calls == [("job-42", None)]
    assert stub.closed is True


def test_render_status_missing_job(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    error = submit_module.RenderJobClientError("Not found", status_code=404)
    stub = _StubRenderClient(error=error)
    monkeypatch.setattr(submit_module, "RenderJobClient", lambda **kwargs: stub)

    result = runner.invoke(app, ["render", "status", "missing-job"])

    assert result.exit_code == 1
    assert isinstance(result.exception, OnePieceExternalServiceError)
    assert "was not found" in str(result.exception)


def test_render_status_http_failure(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
) -> None:
    error = submit_module.RenderJobClientError("Server exploded", status_code=503)
    stub = _StubRenderClient(error=error)
    monkeypatch.setattr(submit_module, "RenderJobClient", lambda **kwargs: stub)

    result = runner.invoke(app, ["render", "status", "job-99", "--farm", "mock"])

    assert result.exit_code == 1
    assert isinstance(result.exception, OnePieceExternalServiceError)
    assert "Server exploded" in str(result.exception)
    assert stub.calls == [("job-99", "mock")]


def test_render_cancel_success(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    log_events: list[tuple[str, str, dict[str, Any]]],
    event_logger: SimpleNamespace,
) -> None:
    stub = _StubRenderClient(
        cancel_response={
            "job_id": "job-77",
            "status": "cancelled",
            "farm_type": "mock",
            "message": "Cancellation accepted",
        }
    )
    monkeypatch.setattr(submit_module, "RenderJobClient", lambda **kwargs: stub)
    monkeypatch.setattr(submit_module, "log", event_logger)

    result = runner.invoke(app, ["render", "cancel", "job-77"])

    assert result.exit_code == 0, result.stdout
    assert "Cancellation status for job-77: cancelled" in result.stdout
    assert "Adapter: mock" in result.stdout
    assert "Message: Cancellation accepted" in result.stdout
    assert stub.cancel_calls == ["job-77"]
    assert stub.closed is True

    events = {(level, event) for level, event, _ in log_events}
    assert ("info", "render.cancel.start") in events
    assert ("info", "render.cancel.success") in events


def test_render_cancel_requires_force_for_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    log_events: list[tuple[str, str, dict[str, Any]]],
    event_logger: SimpleNamespace,
) -> None:
    error = submit_module.RenderJobClientError(
        "Cancellation not supported",
        status_code=409,
        code="render.cancellation_unsupported",
        hint="Retry cancellation in the farm UI.",
    )
    stub = _StubRenderClient(cancel_error=error)
    monkeypatch.setattr(submit_module, "RenderJobClient", lambda **kwargs: stub)
    monkeypatch.setattr(submit_module, "log", event_logger)

    result = runner.invoke(app, ["render", "cancel", "job-101"])

    assert result.exit_code == 1
    assert isinstance(result.exception, OnePieceExternalServiceError)
    message = str(result.exception)
    assert "Render cancellation failed: Cancellation not supported" in message
    assert "Hint: Retry cancellation in the farm UI." in message
    assert stub.cancel_calls == ["job-101"]
    assert stub.closed is True

    events = {(level, event) for level, event, _ in log_events}
    assert ("error", "render.cancel.failed") in events


def test_render_cancel_force_ignores_unsupported(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    log_events: list[tuple[str, str, dict[str, Any]]],
    event_logger: SimpleNamespace,
) -> None:
    error = submit_module.RenderJobClientError(
        "Cancellation not supported",
        status_code=409,
        code="render.cancellation_unsupported",
        hint="Retry cancellation in the farm UI.",
    )
    stub = _StubRenderClient(cancel_error=error)
    monkeypatch.setattr(submit_module, "RenderJobClient", lambda **kwargs: stub)
    monkeypatch.setattr(submit_module, "log", event_logger)

    result = runner.invoke(app, ["render", "cancel", "job-101", "--force"])

    assert result.exit_code == 0, result.stdout
    assert "ignored due to --force" in result.stdout
    assert "Hint: Retry cancellation in the farm UI." in result.stdout
    assert stub.cancel_calls == ["job-101"]
    assert stub.closed is True

    events = {(level, event) for level, event, _ in log_events}
    assert ("warning", "render.cancel.unsupported") in events
    assert ("info", "render.cancel.success") not in events


def test_render_cancel_api_error(
    monkeypatch: pytest.MonkeyPatch,
    runner: CliRunner,
    log_events: list[tuple[str, str, dict[str, Any]]],
    event_logger: SimpleNamespace,
) -> None:
    error = submit_module.RenderJobClientError(
        "Adapter unavailable",
        status_code=502,
        code="adapter.unavailable",
        hint="Wait for the adapter to become healthy.",
    )
    stub = _StubRenderClient(cancel_error=error)
    monkeypatch.setattr(submit_module, "RenderJobClient", lambda **kwargs: stub)
    monkeypatch.setattr(submit_module, "log", event_logger)

    result = runner.invoke(app, ["render", "cancel", "job-202"])

    assert result.exit_code == 1
    assert isinstance(result.exception, OnePieceExternalServiceError)
    message = str(result.exception)
    assert "Render cancellation failed: Adapter unavailable" in message
    assert "Hint: Wait for the adapter to become healthy." in message
    assert stub.cancel_calls == ["job-202"]
    assert stub.closed is True

    events = {(level, event) for level, event, _ in log_events}
    assert ("error", "render.cancel.failed") in events
