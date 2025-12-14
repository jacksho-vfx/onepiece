"""Unit tests for the Deadline render adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from libraries.automation.render import config as render_config
from libraries.automation.render import deadline
from libraries.automation.render.base import (
    RenderAdapterConfigurationError,
    RenderAdapterError,
    RenderAdapterJobRejectedError,
    RenderAdapterUnavailableError,
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


def test_submit_job_attaches_bundle_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = FakeDeadlineClient()
    _patch_client(monkeypatch, client)

    bundle_dir = tmp_path / "bundle"
    layers = bundle_dir / "layers"
    layers.mkdir(parents=True)
    scene = layers / "shot.usda"
    scene.write_text("#usda 1.0", encoding="utf-8")

    manifest = bundle_dir / "bundle_manifest.json"
    manifest.write_text(
        """
{
  "root_layer": "layers/shot.usda",
  "version_hash": "abcd1234",
  "artifacts": []
}
""".strip(),
        encoding="utf-8",
    )

    result = deadline.submit_job(
        scene=str(scene),
        frames="1-10",
        output="/tmp/output",
        dcc="maya",
        priority=70,
        user="nami",
        chunk_size=None,
    )

    job_info = cast(dict[str, object], client.payloads[0]["JobInfo"])
    assert job_info.get("ExtraInfoKeyValue0") == "bundle_version=abcd1234"
    assert job_info.get("ExtraInfoKeyValue1") == f"bundle_manifest={manifest}"
    assert result["job_id"] == "abcd1234"


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


def test_get_job_status_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    class StatusClient:
        base_url = "http://deadline"

        def get_job(self, job_id: str) -> Any:
            return {"jobId": job_id, "status": "rendering", "message": "working"}

    _patch_client(monkeypatch, StatusClient())

    result = deadline.get_job_status("abcd1234")

    assert result == {
        "job_id": "abcd1234",
        "status": "rendering",
        "farm_type": "deadline",
        "message": "working",
    }


def test_get_job_status_raises_for_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ErrorClient:
        base_url = "http://deadline"

        def get_job(self, job_id: str) -> Any:
            raise deadline.DeadlineResponseError("no job")

    _patch_client(monkeypatch, ErrorClient())

    with pytest.raises(RenderAdapterError):
        deadline.get_job_status("missing")


def test_get_job_status_raises_for_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OfflineClient:
        base_url = "http://deadline"

        def get_job(self, job_id: str) -> Any:
            raise deadline.DeadlineUnavailableError("offline")

    _patch_client(monkeypatch, OfflineClient())

    with pytest.raises(RenderAdapterUnavailableError):
        deadline.get_job_status("abcd1234")


def test_cancel_job_happy_path_updates_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CancelClient:
        base_url = "http://deadline"

        def delete_job(self, job_id: str) -> Any:
            return {"status": "cancelled", "message": "stopped"}

    deadline._CAPABILITIES_CACHE = None
    _patch_client(monkeypatch, CancelClient())

    result = deadline.cancel_job("abcd1234")

    assert result == {
        "job_id": "abcd1234",
        "status": "cancelled",
        "farm_type": "deadline",
        "message": "stopped",
    }
    assert deadline._CAPABILITIES_CACHE is not None
    assert deadline._CAPABILITIES_CACHE[1]["cancellation_supported"] is True


def test_cancel_job_raises_for_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RejectClient:
        base_url = "http://deadline"

        def delete_job(self, job_id: str) -> Any:
            raise deadline.DeadlineValidationError("busy")

    _patch_client(monkeypatch, RejectClient())

    with pytest.raises(RenderAdapterJobRejectedError):
        deadline.cancel_job("abcd1234")
