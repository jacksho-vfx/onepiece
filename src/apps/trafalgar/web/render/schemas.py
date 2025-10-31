"""Pydantic models powering the Trafalgar render API."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Callable, ClassVar, Collection, Sequence

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from apps.onepiece.render.submit import DCC_CHOICES, FARM_ADAPTERS


class PriorityCapabilityDescriptor(BaseModel):
    """Describe the priority range supported by a render adapter."""

    default: int | None = Field(
        None,
        description="Default priority applied when a request omits an explicit value.",
    )
    minimum: int | None = Field(
        None, description="Lowest accepted priority value for the adapter."
    )
    maximum: int | None = Field(
        None, description="Highest accepted priority value for the adapter."
    )


class ChunkingCapabilityDescriptor(BaseModel):
    """Describe how a render adapter handles frame chunk sizing."""

    enabled: bool = Field(
        False,
        description="Whether the adapter supports chunking frames into smaller batches.",
    )
    minimum: int | None = Field(
        None,
        description="Smallest chunk size accepted when chunking is enabled.",
    )
    maximum: int | None = Field(
        None,
        description="Largest chunk size accepted when chunking is enabled.",
    )
    default: int | None = Field(
        None, description="Default chunk size applied when chunking is enabled."
    )


class CancellationCapabilityDescriptor(BaseModel):
    """Describe whether an adapter exposes job cancellation APIs."""

    supported: bool = Field(
        False,
        description="Whether the adapter implements cancellation for in-flight jobs.",
    )


class FarmCapabilities(BaseModel):
    """Structured capability metadata exposed for an adapter."""

    priority: PriorityCapabilityDescriptor = Field(
        default_factory=PriorityCapabilityDescriptor,
        description="Priority handling characteristics for the adapter.",
    )
    chunking: ChunkingCapabilityDescriptor = Field(
        default_factory=ChunkingCapabilityDescriptor,
        description="Chunk sizing behaviour supported by the adapter.",
    )
    cancellation: CancellationCapabilityDescriptor = Field(
        default_factory=CancellationCapabilityDescriptor,
        description="Cancellation support advertised by the adapter.",
    )


class FarmInfo(BaseModel):
    """Metadata describing a render farm adapter."""

    name: str = Field(..., description="Adapter key used to submit jobs to the farm.")
    description: str = Field(
        ..., description="Human readable summary of the render farm adapter."
    )
    capabilities: FarmCapabilities = Field(
        default_factory=FarmCapabilities,
        description="Capabilities exposed by the adapter via the OnePiece API.",
    )


class FarmsResponse(BaseModel):
    """Envelope returned when listing render farm adapters."""

    farms: Sequence[FarmInfo]


class RenderJobRequest(BaseModel):
    """Request payload mirroring the CLI submission options."""

    _farm_registry_provider: ClassVar[Callable[[], Collection[str]]] = staticmethod(
        lambda: tuple(FARM_ADAPTERS)
    )

    _FRAME_SEGMENT_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?P<start>-?\d+)(?:-(?P<end>-?\d+)(?:x(?P<step>\d+))?)?$"
    )

    dcc: str = Field(
        ..., description="Digital content creation package (e.g. maya, nuke)."
    )
    scene: str = Field(
        ..., description="Path to the scene file that should be rendered."
    )
    frames: str = Field(
        "1-100",
        description="Frame range to render, supporting Deadline style notation (e.g. 1-100x2).",
    )
    output: str = Field(..., description="Directory for rendered frames.")
    farm: str = Field(
        "mock",
        description="Render farm to submit to (see /farms for the available adapters).",
    )
    priority: int | None = Field(
        None,
        ge=0,
        description="Render job priority communicated to the adapter (defaults to adapter metadata).",
    )
    chunk_size: int | None = Field(
        None,
        ge=1,
        description="Frames per chunk to dispatch when supported by the adapter.",
    )
    user: str | None = Field(
        None,
        description="Submitting user; defaults to the service account if omitted.",
    )

    @field_validator("dcc")
    @classmethod
    def _normalise_dcc(cls, value: str) -> str:
        text = value.strip().lower()
        if text not in DCC_CHOICES:
            raise ValueError(
                f"Unsupported DCC '{value}'. Choose one of: {', '.join(sorted(DCC_CHOICES))}."
            )
        return text

    @classmethod
    def configure_farm_registry(cls, provider: Callable[[], Collection[str]]) -> None:
        """Inject the callable used to resolve registered farm adapters."""

        cls._farm_registry_provider = provider

    @field_validator("farm")
    @classmethod
    def _normalise_farm(cls, value: str, info: ValidationInfo) -> str:
        text = value.strip().lower()
        registry: Collection[str] | None = None
        if info.context is not None:
            registry = info.context.get("farm_registry")
        if registry is None:
            registry = cls._farm_registry_provider()
        if text not in registry:
            raise ValueError(
                f"Unknown farm '{value}'. Choose one of: {', '.join(sorted(registry))}."
            )
        return text

    @field_validator("scene", "output", "frames", "user", mode="before")
    @classmethod
    def _strip_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("Value cannot be empty.")
        return text

    @field_validator("frames")
    @classmethod
    def _validate_frames(cls, value: str) -> str:
        segments = [segment.strip() for segment in value.split(",")]
        if not segments or any(not segment for segment in segments):
            raise ValueError(
                "Frame range must be a comma separated list of frames or ranges (e.g. 1-10,20-30x2)."
            )
        for segment in segments:
            match = cls._FRAME_SEGMENT_PATTERN.match(segment)
            if match is None:
                raise ValueError(
                    "Frame range must use Deadline notation (e.g. 1-10,20-30x2)."
                )
            end_text = match.group("end")
            if end_text is not None:
                start = int(match.group("start"))
                end = int(end_text)
                if end < start:
                    raise ValueError(
                        "Frame ranges must increase from the start frame to the end frame."
                    )
            step_text = match.group("step")
            if step_text is not None:
                step = int(step_text)
                if step <= 0:
                    raise ValueError("Frame range step must be greater than zero.")
        return ",".join(segments)


class RenderJobResponse(BaseModel):
    """Response payload describing the outcome of a render submission."""

    job_id: str = Field(
        ..., description="Identifier returned by the render farm (if any)."
    )
    status: str = Field(
        ..., description="Submission status reported by the render farm."
    )
    farm_type: str = Field(
        ..., description="Render farm adapter that processed the submission."
    )
    message: str | None = Field(
        None,
        description="Optional detail returned by the adapter (for example not implemented notices).",
    )


class RenderJobMetadata(BaseModel):
    """Structured metadata about a submitted render job."""

    job_id: str = Field(..., description="Job identifier returned by the adapter.")
    farm: str = Field(..., description="Registered adapter key handling the job.")
    farm_type: str = Field(..., description="Adapter type reported by the farm.")
    status: str = Field(..., description="Current status reported for the job.")
    message: str | None = Field(
        None, description="Optional status message provided by the adapter."
    )
    request: RenderJobRequest = Field(
        ..., description="Original submission payload for the job."
    )
    submitted_at: datetime = Field(
        ..., description="UTC timestamp recording when the job was stored."
    )


class JobsListResponse(BaseModel):
    """Envelope returned when listing render jobs."""

    jobs: Sequence[RenderJobMetadata]


class DurationMetrics(BaseModel):
    """Summarise accumulated and average durations in seconds."""

    total_seconds: float = Field(
        0.0, description="Total seconds accumulated across matching records."
    )
    average_seconds: float | None = Field(
        None, description="Average duration per record if available."
    )


class RenderStatusAnalytics(BaseModel):
    """Analytics describing job activity for a particular status."""

    count: int = Field(
        0, description="Number of jobs that have entered this status at least once."
    )
    active: int = Field(
        0, description="Number of jobs currently reporting this status."
    )
    last_updated_at: datetime | None = Field(
        None, description="Most recent update timestamp for jobs in this status."
    )
    durations: DurationMetrics = Field(
        default_factory=DurationMetrics,
        description="Aggregated timing information for the status.",
    )


class RenderAdapterAnalytics(BaseModel):
    """Analytics summarising job activity for a render adapter."""

    total_jobs: int = Field(
        0, description="Total number of jobs tracked for the adapter."
    )
    statuses: dict[str, int] = Field(
        default_factory=dict,
        description="Current job counts grouped by status.",
    )
    completed_jobs: int = Field(
        0, description="Number of jobs that have reached a terminal status."
    )
    average_completion_seconds: float | None = Field(
        None,
        description="Average submission-to-completion duration for completed jobs.",
    )
    first_submission_at: datetime | None = Field(
        None,
        description="Timestamp of the earliest recorded submission for the adapter.",
    )
    last_submission_at: datetime | None = Field(
        None, description="Timestamp of the most recent submission for the adapter."
    )


class RenderWindowAnalytics(BaseModel):
    """Analytics summarising submissions within a rolling window."""

    total_jobs: int = Field(
        0, description="Number of jobs submitted within the time window."
    )
    completed_jobs: int = Field(
        0, description="Number of jobs submitted in the window that have completed."
    )
    average_completion_seconds: float | None = Field(
        None,
        description="Average completion duration for jobs submitted in the window.",
    )


class RenderAnalyticsResponse(BaseModel):
    """Aggregated analytics derived from render job history."""

    generated_at: datetime = Field(
        ..., description="UTC timestamp indicating when the analytics were computed."
    )
    total_jobs: int = Field(
        ..., description="Total number of jobs tracked by the service."
    )
    statuses: dict[str, RenderStatusAnalytics] = Field(
        default_factory=dict,
        description="Aggregated analytics grouped by job status.",
    )
    adapters: dict[str, RenderAdapterAnalytics] = Field(
        default_factory=dict,
        description="Aggregated analytics grouped by render adapter.",
    )
    submission_windows: dict[str, RenderWindowAnalytics] = Field(
        default_factory=dict,
        description="Aggregated analytics grouped by submission time window.",
    )


class APIErrorDetail(BaseModel):
    """Standardised error payload returned by the render API."""

    code: str = Field(
        ..., description="Machine readable error code identifying the failure."
    )
    message: str = Field(..., description="Human readable summary of what went wrong.")
    hint: str | None = Field(
        None, description="Optional remediation guidance for operators."
    )
    context: dict[str, Any] | None = Field(
        None, description="Structured context describing the failing request."
    )


class APIErrorResponse(BaseModel):
    """Envelope returned for failed render API requests."""

    error: APIErrorDetail


__all__ = [
    "PriorityCapabilityDescriptor",
    "ChunkingCapabilityDescriptor",
    "CancellationCapabilityDescriptor",
    "FarmCapabilities",
    "FarmInfo",
    "FarmsResponse",
    "RenderJobRequest",
    "RenderJobResponse",
    "RenderJobMetadata",
    "JobsListResponse",
    "DurationMetrics",
    "RenderStatusAnalytics",
    "RenderAdapterAnalytics",
    "RenderWindowAnalytics",
    "RenderAnalyticsResponse",
    "APIErrorDetail",
    "APIErrorResponse",
]
