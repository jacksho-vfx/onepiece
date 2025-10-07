"""Base interfaces and errors for render submission adapters."""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable


class SubmissionResultRequired(TypedDict):
    """Required fields describing a render job submission result."""

    job_id: str
    status: str
    farm_type: str


class SubmissionResult(SubmissionResultRequired, total=False):
    """Render job submission result with optional descriptive metadata."""

    message: str


class AdapterCapabilities(TypedDict, total=False):
    """Describe configurable behaviour supported by a render adapter."""

    default_priority: int
    priority_min: int
    priority_max: int
    chunk_size_enabled: bool
    chunk_size_min: int
    chunk_size_max: int
    default_chunk_size: int


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
        chunk_size: int | None,
    ) -> SubmissionResult:
        """Submit a job to a render farm and return identifying metadata."""


__all__ = [
    "AdapterCapabilities",
    "RenderSubmissionError",
    "RenderSubmitter",
    "SubmissionResult",
]
