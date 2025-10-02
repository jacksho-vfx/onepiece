"""Base interfaces and errors for render submission adapters."""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable


class SubmissionResult(TypedDict):
    """Typed dictionary describing a render job submission result."""

    job_id: str
    status: str
    farm_type: str


class RenderSubmissionError(RuntimeError):
    """Raised when a render job cannot be submitted."""


@runtime_checkable
class RenderSubmitter(Protocol):
    """Protocol implemented by render submission adapters."""

    def submit_job(
        self,
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
    ) -> SubmissionResult:
        """Submit a job to a render farm and return identifying metadata."""


__all__ = [
    "RenderSubmissionError",
    "RenderSubmitter",
    "SubmissionResult",
]
