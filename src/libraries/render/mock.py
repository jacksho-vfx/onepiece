"""Mock render farm submission adapter."""

from __future__ import annotations

import uuid

import structlog

from .base import SubmissionResult

log = structlog.get_logger(__name__)


def submit_job(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
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
    )
    return SubmissionResult(job_id=job_id, status="submitted", farm_type="mock")
