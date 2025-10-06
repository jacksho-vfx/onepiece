"""Deadline render farm submission adapter stub."""

from __future__ import annotations

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
        status="not_implemented",
    )
    return SubmissionResult(
        job_id="",
        status="not_implemented",
        farm_type="deadline",
        message=message,
    )
