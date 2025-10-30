"""Unit tests for the Tractor render adapter."""

from __future__ import annotations

from typing import Any

import pytest

from libraries.automation.render import config as render_config
from libraries.automation.render import tractor
from libraries.automation.render.base import (
    RenderAdapterConfigurationError,
    RenderAdapterError,
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
)


@pytest.fixture(autouse=True)
def reset_tractor_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Ensure tests start with clean caches and environment."""

    render_config.get_adapter_settings.cache_clear()
    monkeypatch.delenv("RENDER_TRACTOR_USERNAME", raising=False)
    monkeypatch.delenv("RENDER_TRACTOR_PASSWORD", raising=False)
    monkeypatch.delenv("RENDER_TRACTOR_URL", raising=False)
    monkeypatch.delenv("RENDER_TRACTOR_HOST", raising=False)
    monkeypatch.setattr(tractor, "_CAPABILITIES_CACHE", None)
    yield
    render_config.get_adapter_settings.cache_clear()
    monkeypatch.setattr(tractor, "_CAPABILITIES_CACHE", None)


class FakeTractorClient:
    """Simple Tractor client stub for testing."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.limit_requests = 0
        self.base_url = "http://tractor"

    def submit_job(self, payload: Any) -> Any:
        self.payloads.append(payload)
        return {"jobId": "job-123", "status": "queued", "message": "queued"}

    def get_job(self, job_id: str) -> Any:
        return {"jobId": job_id, "status": "running", "message": "working"}

    def cancel_job(self, job_id: str) -> Any:
        return {"status": "cancelled", "message": "stopped"}

    def get_limits(self) -> Any:
        self.limit_requests += 1
        return {
            "priority": {"default": 80, "min": 10, "max": 120},
            "chunking": {"enabled": True, "default": 6, "min": 1, "max": 24},
            "cancellation": {"supported": True},
        }


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(tractor, "_get_client", lambda: client)


def test_submit_job_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTractorClient()
    _patch_client(monkeypatch, client)

    result = tractor.submit_job(
        scene="/path/to/scene.mb",
        frames="1-10",
        output="/tmp/output",
        dcc="maya",
        priority=70,
        user="nami",
        chunk_size=5,
    )

    assert result == {
        "job_id": "job-123",
        "status": "queued",
        "farm_type": "tractor",
        "message": "queued",
    }
    assert client.payloads[0]["task"]["chunkSize"] == 5  # type: ignore[index]
    assert client.payloads[0]["job"]["priority"] == 70  # type: ignore[index]


def test_submit_job_raises_for_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    class AuthFailClient:
        base_url = "http://tractor"

        def submit_job(self, payload: Any) -> Any:
            raise tractor.TractorAuthenticationError("bad credentials")

    _patch_client(monkeypatch, AuthFailClient())

    with pytest.raises(RenderAdapterConfigurationError):
        tractor.submit_job(
            scene="/scene.mb",
            frames="1",
            output="/tmp",
            dcc="maya",
            priority=10,
            user="nami",
            chunk_size=None,
        )


def test_submit_job_raises_for_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    class ValidationFailClient:
        base_url = "http://tractor"

        def submit_job(self, payload: Any) -> Any:
            raise tractor.TractorValidationError("frames invalid")

    _patch_client(monkeypatch, ValidationFailClient())

    with pytest.raises(RenderAdapterJobRejectedError):
        tractor.submit_job(
            scene="/scene.mb",
            frames="1",
            output="/tmp",
            dcc="maya",
            priority=10,
            user="nami",
            chunk_size=None,
        )


def test_get_capabilities_queries_tractor_once(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTractorClient()
    _patch_client(monkeypatch, client)

    first = tractor.get_capabilities()
    second = tractor.get_capabilities()

    assert client.limit_requests == 1
    assert first == second
    assert first["default_priority"] == 80
    assert first["cancellation_supported"] is True


def test_get_capabilities_falls_back_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableClient:
        base_url = "http://tractor"

        def get_limits(self) -> Any:
            raise tractor.TractorUnavailableError("offline")

    _patch_client(monkeypatch, UnavailableClient())

    caps = tractor.get_capabilities()
    assert caps["default_priority"] == 75
    assert caps["cancellation_supported"] is False


def test_get_job_status_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeTractorClient()
    _patch_client(monkeypatch, client)

    result = tractor.get_job_status("job-123")

    assert result == {
        "job_id": "job-123",
        "status": "running",
        "farm_type": "tractor",
        "message": "working",
    }


def test_get_job_status_raises_for_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ErrorClient:
        base_url = "http://tractor"

        def get_job(self, job_id: str) -> Any:
            raise tractor.TractorResponseError("no job")

    _patch_client(monkeypatch, ErrorClient())

    with pytest.raises(RenderAdapterError):
        tractor.get_job_status("job-123")


def test_get_job_status_raises_for_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OfflineClient:
        base_url = "http://tractor"

        def get_job(self, job_id: str) -> Any:
            raise tractor.TractorUnavailableError("offline")

    _patch_client(monkeypatch, OfflineClient())

    with pytest.raises(RenderAdapterUnavailableError):
        tractor.get_job_status("job-123")


def test_cancel_job_happy_path_updates_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeTractorClient()
    _patch_client(monkeypatch, client)

    result = tractor.cancel_job("job-123")

    assert result == {
        "job_id": "job-123",
        "status": "cancelled",
        "farm_type": "tractor",
        "message": "stopped",
    }
    assert tractor._CAPABILITIES_CACHE is not None
    assert tractor._CAPABILITIES_CACHE[1]["cancellation_supported"] is True


def test_cancel_job_raises_for_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    class RejectClient:
        base_url = "http://tractor"

        def cancel_job(self, job_id: str) -> Any:
            raise tractor.TractorValidationError("busy")

    _patch_client(monkeypatch, RejectClient())

    with pytest.raises(RenderAdapterJobRejectedError):
        tractor.cancel_job("job-123")

