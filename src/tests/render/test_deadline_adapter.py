"""Unit tests for the Deadline render adapter."""

from __future__ import annotations

import pytest
from typing import Any

from libraries.automation.render import config as render_config
from libraries.automation.render import deadline
from libraries.automation.render.base import (
    RenderAdapterConfigurationError,
    RenderAdapterJobRejectedError,
)


@pytest.fixture(autouse=True)
def reset_deadline_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Ensure tests start with clean caches and environment."""

    render_config.get_adapter_settings.cache_clear()
    monkeypatch.delenv("RENDER_DEADLINE_POOL", raising=False)
    monkeypatch.delenv("RENDER_DEADLINE_USERNAME", raising=False)
    monkeypatch.delenv("RENDER_DEADLINE_PASSWORD", raising=False)
    monkeypatch.delenv("RENDER_DEADLINE_URL", raising=False)
    monkeypatch.delenv("RENDER_DEADLINE_HOST", raising=False)
    monkeypatch.setattr(deadline, "_CAPABILITIES_CACHE", None)
    yield
    render_config.get_adapter_settings.cache_clear()
    monkeypatch.setattr(deadline, "_CAPABILITIES_CACHE", None)


class FakeDeadlineClient:
    """Simple Deadline client stub for testing."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []
        self.limit_requests = 0
        self.base_url = "http://deadline"

    def submit_job(self, payload: Any) -> Any:
        self.payloads.append(payload)
        return {"jobId": "abcd1234", "status": "queued", "message": "queued"}

    def get_limits(self) -> Any:
        self.limit_requests += 1
        return {
            "priority": {"default": 65, "min": 10, "max": 90},
            "chunkSize": {"enabled": True, "default": 5, "min": 1, "max": 20},
            "cancellation": {"supported": True},
        }


def _patch_client(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(deadline, "_get_client", lambda: client)


def test_submit_job_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeDeadlineClient()
    _patch_client(monkeypatch, client)
    monkeypatch.setenv("RENDER_DEADLINE_POOL", "farm-a")
    render_config.get_adapter_settings.cache_clear()

    result = deadline.submit_job(
        scene="/path/to/scene.mb",
        frames="1-10",
        output="/tmp/output",
        dcc="maya",
        priority=70,
        user="nami",
        chunk_size=5,
    )

    assert result == {
        "job_id": "abcd1234",
        "status": "queued",
        "farm_type": "deadline",
        "message": "queued",
    }
    assert client.payloads[0]["JobInfo"]["Pool"] == "farm-a"  # type: ignore[index]
    assert client.payloads[0]["JobInfo"]["ChunkSize"] == 5  # type: ignore[index]


def test_submit_job_raises_for_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    class AuthFailClient:
        base_url = "http://deadline"

        def submit_job(
            self, payload: Any
        ) -> (
            deadline.DeadlineAuthenticationError
        ):  # pragma: no cover - exercised indirectly
            raise deadline.DeadlineAuthenticationError("bad credentials")

    _patch_client(monkeypatch, AuthFailClient())

    with pytest.raises(RenderAdapterConfigurationError):
        deadline.submit_job(
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
        base_url = "http://deadline"

        def submit_job(
            self, payload: Any
        ) -> (
            deadline.DeadlineValidationError
        ):  # pragma: no cover - exercised indirectly
            raise deadline.DeadlineValidationError("frames invalid")

    _patch_client(monkeypatch, ValidationFailClient())

    with pytest.raises(RenderAdapterJobRejectedError):
        deadline.submit_job(
            scene="/scene.mb",
            frames="1",
            output="/tmp",
            dcc="maya",
            priority=10,
            user="nami",
            chunk_size=None,
        )


def test_get_capabilities_queries_deadline_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeDeadlineClient()
    _patch_client(monkeypatch, client)

    first = deadline.get_capabilities()
    second = deadline.get_capabilities()

    assert client.limit_requests == 1
    assert first == second
    assert first["default_priority"] == 65
    assert first["cancellation_supported"] is True


def test_get_capabilities_falls_back_when_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableClient:
        base_url = "http://deadline"

        def get_limits(
            self,
        ) -> (
            deadline.DeadlineUnavailableError
        ):  # pragma: no cover - exercised indirectly
            raise deadline.DeadlineUnavailableError("offline")

    _patch_client(monkeypatch, UnavailableClient())

    caps = deadline.get_capabilities()
    assert caps["default_priority"] == 50
    assert caps["cancellation_supported"] is False
