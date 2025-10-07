"""Deadline render farm submission adapter stub."""

from __future__ import annotations

import structlog

from .base import AdapterCapabilities, SubmissionResult

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
    """Log the intent to submit a Deadline job and raise not implemented."""

    message = "Deadline adapter is not implemented yet."
    log.info(
        "render.deadline.submit_job",
        scene=scene,
        frames=frames,
        output=output,
        dcc=dcc,
        priority=priority,
        user=user,
        chunk_size=chunk_size,
        status="not_implemented",
    )
    return SubmissionResult(
        job_id="",
        status="not_implemented",
        farm_type="deadline",
        message=message,
    )


def get_capabilities() -> AdapterCapabilities:
    """Return estimated capabilities for the Deadline adapter stub."""

    return AdapterCapabilities(
        default_priority=50,
        priority_min=0,
        priority_max=100,
        chunk_size_enabled=True,
        chunk_size_min=1,
        chunk_size_max=50,
        default_chunk_size=10,
    )
