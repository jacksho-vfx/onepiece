"""Tests for dynamic render adapter registration metadata handling."""

from __future__ import annotations

from apps.trafalgar.web.render import RenderSubmissionService
from libraries.automation.render.base import SubmissionResult
from libraries.automation.render.models import RenderAdapter


def _make_adapter(job_id: str) -> RenderAdapter:
    def _adapter(
        *,
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> SubmissionResult:
        return {
            "job_id": job_id,
            "status": "queued",
            "farm_type": "test",
        }

    return _adapter


def test_register_adapter_with_capabilities_tracks_source() -> None:
    service = RenderSubmissionService(adapters={})
    adapter = _make_adapter("job-with-capabilities")

    service.register_adapter(
        "bespoke", adapter, capabilities={"default_priority": 50}
    )

    assert service._adapters["bespoke"] is adapter
    assert service._capability_sources["bespoke"] == {"default_priority": 50}


def test_register_adapter_with_provider_tracks_source() -> None:
    service = RenderSubmissionService(adapters={})
    adapter = _make_adapter("job-with-provider")

    def provider() -> dict[str, int]:
        return {"default_priority": 10}

    service.register_adapter("bespoke", adapter, capability_provider=provider)

    assert service._adapters["bespoke"] is adapter
    assert service._capability_sources["bespoke"] is provider


def test_register_adapter_without_capabilities_removes_stale_metadata() -> None:
    service = RenderSubmissionService(adapters={})
    adapter = _make_adapter("job-initial")

    service.register_adapter(
        "bespoke", adapter, capabilities={"default_priority": 70}
    )

    assert "bespoke" in service._capability_sources

    replacement_adapter = _make_adapter("job-replacement")
    service.register_adapter("bespoke", replacement_adapter)

    assert service._adapters["bespoke"] is replacement_adapter
    assert "bespoke" not in service._capability_sources
