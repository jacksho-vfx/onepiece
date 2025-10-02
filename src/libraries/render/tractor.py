"""Tractor render farm submission adapter stub."""

from __future__ import annotations

import structlog

from .base import RenderSubmissionError, SubmissionResult

log = structlog.get_logger(__name__)


def submit_job(
    scene: str,
    frames: str,
    output: str,
    dcc: str,
    priority: int,
    user: str,
) -> SubmissionResult:
    """Log the intent to submit a Tractor job and raise not implemented."""

    log.info(
        "render.tractor.submit_job",
        scene=scene,
        frames=frames,
        output=output,
        dcc=dcc,
        priority=priority,
        user=user,
    )
    raise RenderSubmissionError("Tractor adapter is not implemented yet.")
