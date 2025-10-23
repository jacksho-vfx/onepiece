"""OpenCue render farm submission adapter stub."""

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
    """Log the intent to submit an OpenCue job and raise not implemented."""

    message = "OpenCue adapter is not implemented yet."
    log.info(
        "render.opencue.submit_job",
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
        hint="Switch to the mock adapter for local development or configure the OpenCue integration.",
        context={
            "adapter": "opencue",
            "scene": scene,
            "dcc": dcc,
        },
    )


def get_capabilities() -> AdapterCapabilities:
    """Return estimated capabilities for the OpenCue adapter stub."""

    return AdapterCapabilities(
        default_priority=60,
        priority_min=0,
        priority_max=120,
        chunk_size_enabled=True,
        chunk_size_min=1,
        chunk_size_max=25,
        default_chunk_size=6,
        cancellation_supported=False,
    )
