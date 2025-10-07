"""Base interfaces and errors for render submission adapters."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, TypedDict, runtime_checkable


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

    def __init__(
        self,
        message: str,
        *,
        code: str = "render.error",
        hint: str | None = None,
        status_code: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint
        self.status_code = status_code
        self.context: dict[str, Any] = dict(context or {})


class RenderAdapterError(RenderSubmissionError):
    """Base class for errors raised by render adapters."""

    default_code = "adapter.error"
    default_status = 502

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        hint: str | None = None,
        status_code: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            code=code or self.default_code,
            hint=hint,
            status_code=status_code or self.default_status,
            context=context,
        )


class RenderAdapterConfigurationError(RenderAdapterError):
    """Raised when an adapter rejects the submission payload."""

    default_code = "adapter.configuration_error"
    default_status = 400


class RenderAdapterUnavailableError(RenderAdapterError):
    """Raised when an adapter cannot communicate with the farm."""

    default_code = "adapter.unavailable"
    default_status = 503


class RenderAdapterNotImplementedError(RenderAdapterError):
    """Raised when an adapter has not been implemented yet."""

    default_code = "adapter.not_implemented"
    default_status = 501


class RenderAdapterJobRejectedError(RenderAdapterError):
    """Raised when the farm rejects the submitted job."""

    default_code = "adapter.job_rejected"
    default_status = 409


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
    "RenderAdapterConfigurationError",
    "RenderAdapterError",
    "RenderAdapterJobRejectedError",
    "RenderAdapterNotImplementedError",
    "RenderAdapterUnavailableError",
    "RenderSubmissionError",
    "RenderSubmitter",
    "SubmissionResult",
]
