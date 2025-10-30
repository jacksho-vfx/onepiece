"""Unit tests for the OpenCue render adapter."""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from libraries.automation.render import config as render_config
from libraries.automation.render import opencue
from libraries.automation.render.base import (
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
)


@pytest.fixture(autouse=True)
def reset_opencue_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Ensure tests start with clean caches and environment."""

    render_config.get_adapter_settings.cache_clear()
    monkeypatch.delenv("RENDER_OPENCUE_SHOW", raising=False)
    monkeypatch.delenv("RENDER_OPENCUE_POOL", raising=False)
    monkeypatch.delenv("RENDER_OPENCUE_FACILITY", raising=False)
    monkeypatch.delenv("RENDER_OPENCUE_TOKEN", raising=False)
    monkeypatch.delenv("RENDER_OPENCUE_URL", raising=False)
    monkeypatch.delenv("RENDER_OPENCUE_HOST", raising=False)
    monkeypatch.setattr(opencue, "_CAPABILITIES_CACHE", None)
    yield
    render_config.get_adapter_settings.cache_clear()
    monkeypatch.setattr(opencue, "_CAPABILITIES_CACHE", None)


class FakeOpenCueClient:
    """Simple OpenCue client stub for testing."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []
        self.limit_requests = 0
        self.base_url = "http://opencue"

    def submit_job(self, payload: Mapping[str, Any]) -> Any:
        self.payloads.append(dict(payload))
        return {"id": "job-123", "status": "queued", "message": "queued"}

    def get_job(self, job_id: str) -> Any:
        return {"id": job_id, "status": "running", "message": "working"}

    def cancel_job(self, job_id: str) -> Any:
        return {"status": "cancelled", "message": "stopped"}

    def get_limits(self) -> Any:
        self.limit_requests += 1
        return {
            "priority": {"default": 70, "min": 10, "max": 90},
            "chunk": {"enabled": True, "default": 8, "min": 1, "max": 16},
            "cancellation": {"supported": True},
        }


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(opencue, "_get_client", lambda: client)


def test_submit_job_builds_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenCueClient()
    _patch_client(monkeypatch, client)
    monkeypatch.setenv("RENDER_OPENCUE_SHOW", "onepiece")
    monkeypatch.setenv("RENDER_OPENCUE_POOL", "farm-b")
    render_config.get_adapter_settings.cache_clear()

    result = opencue.submit_job(
        scene="/path/to/scene.mb",
        frames="1-5",
        output="/tmp/output",
        dcc="maya",
        priority=55,
        user="nami",
        chunk_size=4,
    )

    assert result == {
        "job_id": "job-123",
        "status": "queued",
        "farm_type": "opencue",
        "message": "queued",
    }
    payload = client.payloads[0]
    assert payload["show"] == "onepiece"
    assert payload["pool"] == "farm-b"
    assert payload["layers"][0]["chunk"] == 4


def test_submit_job_uses_capability_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenCueClient()
    _patch_client(monkeypatch, client)

    result = opencue.submit_job(
        scene="/path/to/scene.mb",
        frames="1-5",
        output="/tmp/output",
        dcc="houdini",
        priority=65,
        user="robin",
        chunk_size=None,
    )

    assert result["job_id"] == "job-123"
    assert client.payloads[0]["layers"][0]["chunk"] == 8


def test_submit_job_raises_for_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    class ValidationClient(FakeOpenCueClient):
        def submit_job(self, payload: Mapping[str, Any]) -> Any:
            raise opencue.OpenCueValidationError("invalid")

    _patch_client(monkeypatch, ValidationClient())

    with pytest.raises(RenderAdapterJobRejectedError):
        opencue.submit_job(
            scene="/scene",
            frames="1",
            output="/output",
            dcc="maya",
            priority=10,
            user="nami",
            chunk_size=None,
        )


def test_get_job_status_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenCueClient()
    _patch_client(monkeypatch, client)

    result = opencue.get_job_status("job-123")

    assert result == {
        "job_id": "job-123",
        "status": "running",
        "farm_type": "opencue",
        "message": "working",
    }


def test_get_job_status_raises_for_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class OfflineClient(FakeOpenCueClient):
        def get_job(self, job_id: str) -> Any:
            raise opencue.OpenCueUnavailableError("offline")

    _patch_client(monkeypatch, OfflineClient())

    with pytest.raises(RenderAdapterUnavailableError):
        opencue.get_job_status("job-123")


def test_cancel_job_updates_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenCueClient()
    _patch_client(monkeypatch, client)

    result = opencue.cancel_job("job-123")

    assert result == {
        "job_id": "job-123",
        "status": "cancelled",
        "farm_type": "opencue",
        "message": "stopped",
    }
    assert opencue._CAPABILITIES_CACHE is not None
    assert opencue._CAPABILITIES_CACHE[1]["cancellation_supported"] is True


def test_get_capabilities_queries_opencue_once(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeOpenCueClient()
    _patch_client(monkeypatch, client)

    first = opencue.get_capabilities()
    second = opencue.get_capabilities()

    assert client.limit_requests == 1
    assert first == second
    assert first["default_priority"] == 70
    assert first["cancellation_supported"] is True


def test_get_capabilities_falls_back_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableClient(FakeOpenCueClient):
        def get_limits(self) -> Any:
            raise opencue.OpenCueUnavailableError("offline")

    _patch_client(monkeypatch, UnavailableClient())

    caps = opencue.get_capabilities()
    assert caps["default_priority"] == 60
    assert caps["cancellation_supported"] is False
