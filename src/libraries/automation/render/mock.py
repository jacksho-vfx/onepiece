"""Mock render farm submission adapter."""

from __future__ import annotations

import uuid

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
    """Simulate submitting a render job by generating a fake job identifier."""

    job_id = f"mock-{uuid.uuid4().hex}"
    log.info(
        "render.mock.submit_job",
        scene=scene,
        frames=frames,
        output=output,
        dcc=dcc,
        priority=priority,
        user=user,
        job_id=job_id,
        chunk_size=chunk_size,
    )
    return SubmissionResult(job_id=job_id, status="submitted", farm_type="mock")


def get_capabilities() -> AdapterCapabilities:
    """Return static capabilities for the mock adapter used in tests."""

    return AdapterCapabilities(
        default_priority=50,
        priority_min=0,
        priority_max=100,
        chunk_size_enabled=True,
        chunk_size_min=1,
        chunk_size_max=10,
        default_chunk_size=5,
        cancellation_supported=False,
    )
