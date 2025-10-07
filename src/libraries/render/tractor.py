"""Tractor render farm submission adapter stub."""

from __future__ import annotations

import structlog

from .base import (
    AdapterCapabilities,
    RenderAdapterNotImplementedError,
    SubmissionResult,
)

log = structlog.get_logger(__name__)


def submit_job(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
    chunk_size: int | None,
) -> SubmissionResult:
    """Log the intent to submit a Tractor job and raise not implemented."""

    message = "Tractor adapter is not implemented yet."
    log.info(
        "render.tractor.submit_job",
        scene=scene,
        frames=frames,
        output=output,
        dcc=dcc,
        priority=priority,
        user=user,
        chunk_size=chunk_size,
        status="not_implemented",
    )
    raise RenderAdapterNotImplementedError(
        message,
        hint="Switch to the mock adapter for local development or configure the Tractor integration.",
        context={
            "adapter": "tractor",
            "scene": scene,
            "dcc": dcc,
        },
    )


def get_capabilities() -> AdapterCapabilities:
    """Return estimated capabilities for the Tractor adapter stub."""

    return AdapterCapabilities(
        default_priority=75,
        priority_min=1,
        priority_max=150,
        chunk_size_enabled=True,
        chunk_size_min=1,
        chunk_size_max=30,
        default_chunk_size=8,
        cancellation_supported=False,
    )
