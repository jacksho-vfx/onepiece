"""FastAPI application exposing render job submission endpoints."""

from __future__ import annotations

import asyncio
import getpass
import os
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
from typing import (
    Any,
    Awaitable,
    Callable,
    Mapping,
    Sequence,
    AsyncGenerator,
    Collection,
    ClassVar,
)

import structlog
from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator
from starlette.responses import Response
from starlette.websockets import WebSocketDisconnect

from apps.onepiece.render.submit import (
    DCC_CHOICES,
    FARM_ADAPTERS,
    FARM_CAPABILITY_PROVIDERS,
    _get_adapter_capabilities,
    _resolve_priority_and_chunk_size,
)
from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceValidationError,
)
from apps.trafalgar.version import TRAFALGAR_VERSION
from libraries.render.base import (
    AdapterCapabilities,
    RenderAdapterUnavailableError,
    RenderSubmissionError,
    SubmissionResult,
)
from libraries.render.models import CapabilityProvider, RenderAdapter

from apps.trafalgar.web.events import EventBroadcaster
from apps.trafalgar.web.job_store import JobStore
from apps.trafalgar.web.security import (
    AuthenticatedPrincipal,
    ROLE_RENDER_MANAGE,
    ROLE_RENDER_READ,
    ROLE_RENDER_SUBMIT,
    create_protected_router,
    require_roles,
)

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialise_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return _utcnow()


FARM_DESCRIPTIONS: Mapping[str, str] = {
    "deadline": "Autodesk Deadline render manager (stub).",
    "tractor": "Pixar Tractor render farm (stub).",
    "opencue": "OpenCue render manager (stub).",
    "mock": "Mock render farm for testing and demos.",
}


TERMINAL_STATUSES: set[str] = {
    "completed",
    "failed",
    "cancelled",
    "aborted",
    "errored",
    "error",
}


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

    name: str = Field(..., description="Adapter identifier used by the API and CLI.")
    description: str = Field(
        ..., description="Human readable description of the adapter."
    )
    capabilities: FarmCapabilities = Field(
        default_factory=FarmCapabilities,
        description="Capability descriptors declared by the adapter.",
    )


class FarmsResponse(BaseModel):
    """Response payload enumerating available render farm adapters."""

    farms: Sequence[FarmInfo]


def _build_farm_capabilities(
    farm: str, capabilities: AdapterCapabilities | None = None
) -> FarmCapabilities:
    """Translate adapter capability metadata into API descriptors."""

    if capabilities is None:
        try:
            raw_capabilities: AdapterCapabilities = _get_adapter_capabilities(farm)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "render.farm.capabilities.unavailable",
                farm=farm,
                error=str(exc),
            )
            return FarmCapabilities()
    else:
        raw_capabilities = dict(capabilities)

    chunk_enabled = raw_capabilities.get("chunk_size_enabled", False)
    default_chunk = raw_capabilities.get("default_chunk_size")
    if not chunk_enabled:
        default_chunk = None

    return FarmCapabilities(
        priority=PriorityCapabilityDescriptor(
            default=raw_capabilities.get("default_priority", 50),
            minimum=raw_capabilities.get("priority_min"),
            maximum=raw_capabilities.get("priority_max"),
        ),
        chunking=ChunkingCapabilityDescriptor(
            enabled=chunk_enabled,
            minimum=raw_capabilities.get("chunk_size_min"),
            maximum=raw_capabilities.get("chunk_size_max"),
            default=default_chunk,
        ),
        cancellation=CancellationCapabilityDescriptor(
            supported=raw_capabilities.get("cancellation_supported", False),
        ),
    )


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
                        f"Frame range segment '{segment}' must have the end greater than or equal to the start."
                    )
                step_text = match.group("step")
                if step_text is not None and int(step_text) <= 0:
                    raise ValueError(
                        f"Frame range segment '{segment}' must use a positive step."
                    )
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

    total_jobs: int = Field(0, description="Total number of jobs tracked for the adapter.")
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
        None, description="Timestamp of the earliest recorded submission for the adapter."
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
    total_jobs: int = Field(..., description="Total number of jobs tracked by the service.")
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


@dataclass
class _JobRecord:
    """Internal storage representation for submitted render jobs."""

    job_id: str
    farm: str
    farm_type: str
    status: str
    message: str | None
    request: RenderJobRequest
    created_at: datetime
    updated_at: datetime | None = None
    completed_at: datetime | None = None
    status_history: list[tuple[str, datetime]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.updated_at is None:
            self.updated_at = self.created_at
        if not self.status_history:
            self.status_history.append((self.status, self.created_at))
        else:
            # Ensure history is sorted for consistent duration calculations.
            self.status_history.sort(key=lambda entry: entry[1])
            last_status, last_timestamp = self.status_history[-1]
            if last_status != self.status:
                marker = self.updated_at or last_timestamp
                self.status_history.append((self.status, marker))
        status_key = (self.status or "").strip().lower()
        if self.completed_at is None and status_key in TERMINAL_STATUSES:
            self.completed_at = self.updated_at

    def status_durations(self, *, now: datetime | None = None) -> dict[str, float]:
        """Return the total seconds spent in each status."""

        if not self.status_history:
            return {}

        durations: dict[str, float] = defaultdict(float)
        moment = now or _utcnow()
        for index, (status, start) in enumerate(self.status_history):
            if index + 1 < len(self.status_history):
                end = self.status_history[index + 1][1]
            else:
                end = self.completed_at or moment
            if end < start:
                continue
            durations[status] += (end - start).total_seconds()
        return dict(durations)

    def snapshot(self) -> RenderJobMetadata:
        return RenderJobMetadata(
            job_id=self.job_id,
            farm=self.farm,
            farm_type=self.farm_type,
            status=self.status,
            message=self.message,
            request=self.request.model_copy(deep=True),
            submitted_at=self.created_at,
        )

    def to_storage(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "farm": self.farm,
            "farm_type": self.farm_type,
            "status": self.status,
            "message": self.message,
            "request": self.request.model_dump(),
            "created_at": self.created_at.astimezone(timezone.utc).isoformat(),
            "updated_at": _serialise_datetime(self.updated_at),
            "completed_at": _serialise_datetime(self.completed_at),
            "status_history": [
                {
                    "status": status,
                    "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
                }
                for status, timestamp in self.status_history
            ],
        }

    @classmethod
    def from_storage(cls, payload: Mapping[str, Any]) -> "_JobRecord":
        created_at_raw = payload.get("created_at")
        created_at = _parse_timestamp(created_at_raw)
        updated_at_raw = payload.get("updated_at")
        updated_at = _parse_timestamp(updated_at_raw) if updated_at_raw else created_at
        completed_at_raw = payload.get("completed_at")
        completed_at = (
            _parse_timestamp(completed_at_raw)
            if completed_at_raw is not None
            else None
        )
        history_payload = payload.get("status_history") or []
        history: list[tuple[str, datetime]] = []
        for entry in history_payload:
            if not isinstance(entry, Mapping):
                continue
            status_value = str(entry.get("status", payload.get("status", "unknown")))
            timestamp_raw = entry.get("timestamp")
            timestamp = (
                _parse_timestamp(timestamp_raw)
                if timestamp_raw is not None
                else created_at
            )
            history.append((status_value, timestamp))
        if not history:
            history.append((str(payload.get("status", "unknown")), created_at))
        return cls(
            job_id=str(payload["job_id"]),
            farm=str(payload["farm"]),
            farm_type=str(payload.get("farm_type", payload["farm"])),
            status=str(payload.get("status", "unknown")),
            message=payload.get("message"),
            request=RenderJobRequest(**payload["request"]),
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
            status_history=history,
        )


JOB_STORE_PATH_ENV = "TRAFALGAR_RENDER_JOBS_PATH"
JOB_HISTORY_LIMIT_ENV = "TRAFALGAR_RENDER_JOBS_HISTORY_LIMIT"
JOB_RETENTION_HOURS_ENV = "TRAFALGAR_RENDER_JOBS_RETENTION_HOURS"
JOB_STATUS_POLL_INTERVAL_ENV = "TRAFALGAR_RENDER_STATUS_POLL_INTERVAL"
JOB_STORE_PERSIST_THROTTLE_ENV = "TRAFALGAR_RENDER_STORE_PERSIST_INTERVAL"

DEFAULT_STATUS_POLL_INTERVAL = 5.0
DEFAULT_STORE_PERSIST_INTERVAL = 1.0


class RenderSubmissionService:
    """Submit render jobs using the shared adapter registry."""

    DEFAULT_SUBMISSION_WINDOWS: ClassVar[Mapping[str, timedelta]] = {
        "1h": timedelta(hours=1),
        "6h": timedelta(hours=6),
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
    }

    def __init__(
        self,
        adapters: Mapping[str, RenderAdapter] | None = None,
        *,
        capability_registry: (
            Mapping[str, CapabilityProvider | AdapterCapabilities] | None
        ) = None,
        job_store: JobStore | None = None,
        history_limit: int | None = None,
        broadcaster: EventBroadcaster | None = None,
        status_poll_interval: float | None = None,
        store_persist_interval: float | None = None,
    ) -> None:
        initial_adapters = adapters or FARM_ADAPTERS
        self._adapters = {
            name.strip().lower(): adapter for name, adapter in initial_adapters.items()
        }
        base_capabilities: dict[str, CapabilityProvider | AdapterCapabilities] = {
            name: provider for name, provider in FARM_CAPABILITY_PROVIDERS.items()
        }
        if capability_registry:
            for name, entry in capability_registry.items():
                base_capabilities[name.strip().lower()] = entry
        self._capability_sources: dict[
            str, CapabilityProvider | AdapterCapabilities
        ] = {}
        for name in self._adapters:
            entry = base_capabilities.get(name)
            if entry is not None:
                self._capability_sources[name] = entry
        self._jobs: OrderedDict[str, _JobRecord] = OrderedDict()
        self._store = job_store
        self._history_limit = (
            history_limit if history_limit and history_limit > 0 else None
        )
        self._events = broadcaster
        self._history_pruned_total = 0
        self._last_history_prune_at: datetime | None = None
        self._last_history_prune_count = 0
        persist_interval_value = (
            store_persist_interval
            if store_persist_interval is not None
            else DEFAULT_STORE_PERSIST_INTERVAL
        )
        self._persist_throttle: timedelta | None = None
        if persist_interval_value and persist_interval_value > 0:
            self._persist_throttle = timedelta(seconds=float(persist_interval_value))
        self._last_persist_at: datetime | None = None
        self._persist_pending = False
        poll_interval_value = (
            status_poll_interval
            if status_poll_interval is not None
            else DEFAULT_STATUS_POLL_INTERVAL
        )
        self._poll_interval: float | None = (
            float(poll_interval_value)
            if poll_interval_value and poll_interval_value > 0
            else None
        )
        self._poll_task: asyncio.Task[None] | None = None
        self._load_jobs()

    def list_farms(self) -> list[FarmInfo]:
        entries: list[FarmInfo] = []
        for name in sorted(self._adapters):
            description = FARM_DESCRIPTIONS.get(
                name, f"Render farm adapter registered as '{name}'."
            )
            capability_data = self._describe_capabilities(name)
            capabilities = _build_farm_capabilities(name, capability_data)
            entries.append(
                FarmInfo(
                    name=name,
                    description=description,
                    capabilities=capabilities,
                )
            )
        return entries

    def _capability_source(
        self, farm: str
    ) -> tuple[AdapterCapabilities | None, CapabilityProvider | None]:
        entry = self._capability_sources.get(farm)
        if entry is None:
            return None, None
        if callable(entry):
            return None, entry
        return dict(entry), None

    def _describe_capabilities(self, farm: str) -> AdapterCapabilities | None:
        capabilities, provider = self._capability_source(farm)
        if capabilities is not None:
            return capabilities
        if provider is None:
            return None
        try:
            return provider() or {}
        except RenderSubmissionError as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "render.farm.capabilities.unavailable",
                farm=farm,
                error=str(exc),
            )
            return None

    def register_adapter(
        self,
        name: str,
        adapter: RenderAdapter,
        *,
        capability_provider: CapabilityProvider | None = None,
        capabilities: AdapterCapabilities | None = None,
    ) -> None:
        """Register or replace a render adapter at runtime."""

        if capability_provider is not None and capabilities is not None:
            raise ValueError(
                "Provide either 'capabilities' or 'capability_provider', not both."
            )
        key = name.strip().lower()
        self._adapters[key] = adapter
        if capabilities is not None:
            self._capability_sources[key] = dict(capabilities)
        elif capability_provider is not None:
            self._capability_sources[key] = capability_provider

    def adapter_keys(self) -> tuple[str, ...]:
        """Return the set of registered adapter identifiers."""

        return tuple(sorted(self._adapters))

    def submit_job(self, request: RenderJobRequest) -> SubmissionResult:
        adapter = self._adapters.get(request.farm)
        if adapter is None:
            raise RenderSubmissionError(
                f"Unknown render farm '{request.farm}'.",
                code="render.farm_not_found",
                status_code=404,
                hint="Use the /farms endpoint to list available adapters and retry with a registered farm key.",
                context={"farm": request.farm},
            )
        resolved_user = request.user or getpass.getuser()
        capability_data, capability_provider = self._capability_source(request.farm)
        if capability_data is None and capability_provider is None:
            capability_data = {}
        try:
            resolved_priority, resolved_chunk, _ = _resolve_priority_and_chunk_size(
                farm=request.farm,
                priority=request.priority,
                chunk_size=request.chunk_size,
                capabilities=capability_data,
                capability_provider=capability_provider,
            )
        except OnePieceValidationError as exc:
            raise RenderSubmissionError(
                str(exc),
                code="render.invalid_request",
                status_code=422,
                hint="Check the farm capabilities and adjust priority or chunk size values before retrying.",
                context={
                    "farm": request.farm,
                    "priority": request.priority,
                    "chunk_size": request.chunk_size,
                },
            ) from exc
        except OnePieceExternalServiceError as exc:
            raise RenderSubmissionError(
                str(exc),
                code="render.capabilities_unavailable",
                status_code=400,
                hint="Retry once the render farm capabilities endpoint is available or contact an administrator.",
                context={
                    "farm": request.farm,
                    "priority": request.priority,
                    "chunk_size": request.chunk_size,
                },
            ) from exc
        result = adapter(
            scene=request.scene,
            frames=request.frames,
            output=request.output,
            dcc=request.dcc,
            priority=resolved_priority,
            user=resolved_user,
            chunk_size=resolved_chunk,
        )
        job_id = result.get("job_id", "")
        stored_request = request.model_copy(
            update={"priority": resolved_priority, "chunk_size": resolved_chunk},
            deep=True,
        )
        record = _JobRecord(
            job_id=job_id,
            farm=request.farm,
            farm_type=result.get("farm_type", request.farm),
            status=result.get("status", "unknown"),
            message=result.get("message"),
            request=stored_request,
            created_at=_utcnow(),
        )
        if job_id:
            self._jobs[job_id] = record
            self._enforce_history_limit()
            self._persist_jobs(force=True)
            self._emit_event("job.created", record)
        return result

    def list_jobs(
        self,
        *,
        limit: int | None = None,
        status: Collection[str] | None = None,
        farm: Collection[str] | None = None,
    ) -> list[RenderJobMetadata]:
        """Return the cached job list filtered by farm and status."""

        if limit is not None and limit <= 0:
            return []

        status_filter: set[str] | None = None
        if status:
            normalised = {value.strip().lower() for value in status if value}
            status_filter = normalised or None

        farm_filter: set[str] | None = None
        if farm:
            normalised = {value.strip().lower() for value in farm if value}
            farm_filter = normalised or None

        jobs: list[RenderJobMetadata] = []
        dirty = False
        for record in self._jobs.values():
            dirty = self._refresh_job(record) or dirty

            if status_filter is not None:
                record_status = (record.status or "").strip().lower()
                if record_status not in status_filter:
                    continue

            if farm_filter is not None:
                record_farm = (record.farm or "").strip().lower()
                if record_farm not in farm_filter:
                    continue

            jobs.append(record.snapshot())

            if limit is not None and len(jobs) >= limit:
                break

        if dirty:
            self._persist_jobs(force=True)
        return jobs

    def get_job(self, job_id: str) -> RenderJobMetadata:
        record = self._jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if self._refresh_job(record):
            self._persist_jobs(force=True)
        return record.snapshot()

    def cancel_job(self, job_id: str) -> RenderJobMetadata:
        record = self._jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        adapter = self._adapters.get(record.farm)
        if adapter is None:
            raise RenderSubmissionError(
                f"Unknown render farm '{record.farm}' for job '{job_id}'.",
                code="render.farm_not_found",
                status_code=404,
                hint="The adapter handling this job is no longer registered with the service.",
                context={"farm": record.farm, "job_id": job_id},
            )
        cancel = getattr(adapter, "cancel_job", None)
        if not callable(cancel):
            raise RenderSubmissionError(
                f"Render farm '{record.farm}' does not support job cancellation.",
                code="render.cancellation_unsupported",
                status_code=409,
                hint="Retry cancellation through the farm's native tooling or use an adapter that exposes cancellation APIs.",
                context={"farm": record.farm, "job_id": job_id},
            )
        try:
            result = cancel(job_id)
        except RenderSubmissionError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.exception("render.job.cancel.error", job_id=job_id, farm=record.farm)
            raise RenderAdapterUnavailableError(
                f"Failed to cancel job '{job_id}' on farm '{record.farm}'.",
                hint="Check connectivity to the render farm and retry the cancellation once the service is healthy.",
                context={"farm": record.farm, "job_id": job_id},
            ) from exc
        if self._update_record_from_result(record, result):
            self._persist_jobs(force=True)
        return record.snapshot()

    def _refresh_job(self, record: _JobRecord) -> bool:
        adapter = self._adapters.get(record.farm)
        if adapter is None:
            return False
        status_lookup = getattr(adapter, "get_job_status", None)
        if not callable(status_lookup):
            return False
        try:
            result = status_lookup(record.job_id)
        except RenderSubmissionError as exc:
            logger.warning(
                "render.job.status.failed",
                job_id=record.job_id,
                farm=record.farm,
                error=str(exc),
            )
            return False
        except Exception:  # pragma: no cover - defensive guard
            logger.exception(
                "render.job.status.error", job_id=record.job_id, farm=record.farm
            )
            return False
        return self._update_record_from_result(record, result)

    def _update_record_from_result(
        self, record: _JobRecord, result: SubmissionResult
    ) -> bool:
        changed = False
        moment: datetime | None = None
        status = result.get("status")
        if status and status != record.status:
            moment = _utcnow()
            record.status = status
            record.status_history.append((status, moment))
            status_key = status.strip().lower()
            if status_key in TERMINAL_STATUSES:
                record.completed_at = moment
            else:
                record.completed_at = None
            changed = True
        if "message" in result and result.get("message") != record.message:
            record.message = result.get("message")
            moment = moment or _utcnow()
            changed = True
        farm_type = result.get("farm_type")
        if farm_type and farm_type != record.farm_type:
            record.farm_type = farm_type
            moment = moment or _utcnow()
            changed = True
        if changed:
            if moment is None:
                moment = _utcnow()
            record.updated_at = moment
            self._emit_event("job.updated", record)
        return changed

    def _load_jobs(self) -> None:
        if not self._store:
            return
        loaded_records = sorted(self._store.load(), key=lambda entry: entry.created_at)
        self._jobs = OrderedDict((record.job_id, record) for record in loaded_records)
        previous_count = len(self._jobs)
        self._enforce_history_limit()
        if self._history_limit is not None and len(self._jobs) < previous_count:
            self._persist_jobs(force=True)

    def _persist_jobs(self, *, force: bool = False) -> None:
        if not self._store:
            self._persist_pending = False
            return
        now = _utcnow()
        if (
            not force
            and self._persist_throttle is not None
            and self._last_persist_at is not None
            and now - self._last_persist_at < self._persist_throttle
        ):
            self._persist_pending = True
            return
        self._store.save(self._jobs.values())
        self._last_persist_at = now
        self._persist_pending = False

    def _enforce_history_limit(self) -> None:
        if self._history_limit is None:
            return
        removed = 0
        while len(self._jobs) > self._history_limit:
            oldest_key, record = self._jobs.popitem(last=False)
            self._emit_event(
                "job.removed",
                record,
                payload_override={"job": {"job_id": record.job_id}},
            )
            removed += 1
        if removed:
            self._last_history_prune_at = _utcnow()
            self._last_history_prune_count = removed
            self._history_pruned_total += removed

    def start_background_polling(self) -> None:
        """Launch the asynchronous poller that refreshes job statuses."""

        if self._poll_interval is None:
            return
        if self._poll_task and not self._poll_task.done():
            return
        loop = asyncio.get_running_loop()
        self._poll_task = loop.create_task(self._run_status_poller())

    async def stop_background_polling(self) -> None:
        """Stop the poller if it is running and flush pending persistence."""

        if not self._poll_task:
            return
        task = self._poll_task
        self._poll_task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run_status_poller(self) -> None:
        assert self._poll_interval is not None
        try:
            while True:
                dirty = False
                for record in list(self._jobs.values()):
                    dirty = self._refresh_job(record) or dirty
                if dirty or self._persist_pending:
                    self._persist_jobs()
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            raise
        finally:
            if self._persist_pending:
                self._persist_jobs(force=True)

    def get_metrics(self) -> dict[str, Any]:
        store_metrics: dict[str, Any] | None = None
        if self._store:
            store_metrics = self._store.stats.to_dict()
        return {
            "history_size": len(self._jobs),
            "history_limit": self._history_limit,
            "history_pruned_total": self._history_pruned_total,
            "last_history_prune_at": _serialise_datetime(self._last_history_prune_at),
            "last_history_pruned": self._last_history_prune_count,
            "store": store_metrics,
        }

    def get_render_analytics(
        self, *, now: datetime | None = None
    ) -> RenderAnalyticsResponse:
        """Compute aggregated analytics for render job history."""

        moment = now or _utcnow()
        records = list(self._jobs.values())

        status_totals: dict[str, dict[str, Any]] = {}
        adapter_totals: dict[str, Any] = {}

        for record in records:
            record_updated = record.updated_at or record.created_at
            durations = record.status_durations(now=moment)
            for status_name, duration_seconds in durations.items():
                status_entry = status_totals.setdefault(
                    status_name,
                    {
                        "count": 0,
                        "total_duration": 0.0,
                        "active": 0,
                        "last_updated": None,
                    },
                )
                status_entry["count"] += 1
                status_entry["total_duration"] += max(duration_seconds, 0.0)
                if record_updated is not None:
                    last_updated: datetime | None = status_entry["last_updated"]
                    if last_updated is None or record_updated > last_updated:
                        status_entry["last_updated"] = record_updated

            status_entry = status_totals.setdefault(
                record.status,
                {
                    "count": 0,
                    "total_duration": 0.0,
                    "active": 0,
                    "last_updated": None,
                },
            )
            status_entry["active"] += 1
            if record_updated is not None:
                last_updated = status_entry["last_updated"]
                if last_updated is None or record_updated > last_updated:
                    status_entry["last_updated"] = record_updated

            adapter_entry = adapter_totals.setdefault(
                record.farm,
                {
                    "total_jobs": 0,
                    "statuses": defaultdict(int),
                    "completed_jobs": 0,
                    "total_completion": 0.0,
                    "first_submission": None,
                    "last_submission": None,
                },
            )
            adapter_entry["total_jobs"] += 1
            adapter_entry["statuses"][record.status] += 1

            created_at = record.created_at
            first_submission: datetime | None = adapter_entry["first_submission"]
            if first_submission is None or created_at < first_submission:
                adapter_entry["first_submission"] = created_at
            last_submission: datetime | None = adapter_entry["last_submission"]
            if last_submission is None or created_at > last_submission:
                adapter_entry["last_submission"] = created_at

            if record.completed_at is not None:
                adapter_entry["completed_jobs"] += 1
                completion_seconds = (
                    record.completed_at - record.created_at
                ).total_seconds()
                adapter_entry["total_completion"] += max(completion_seconds, 0.0)

        status_payload: dict[str, RenderStatusAnalytics] = {}
        for status_name, entry in status_totals.items():
            count = entry["count"]
            active = entry["active"]
            total_duration = entry["total_duration"]
            effective_count = count or active
            average = (
                (total_duration / effective_count)
                if effective_count
                else None
            )
            status_payload[status_name] = RenderStatusAnalytics(
                count=count,
                active=active,
                last_updated_at=entry["last_updated"],
                durations=DurationMetrics(
                    total_seconds=total_duration,
                    average_seconds=average,
                ),
            )

        adapter_payload: dict[str, RenderAdapterAnalytics] = {}
        for adapter_name, entry in adapter_totals.items():
            completed = entry["completed_jobs"]
            total_completion = entry["total_completion"]
            adapter_payload[adapter_name] = RenderAdapterAnalytics(
                total_jobs=entry["total_jobs"],
                statuses=dict(entry["statuses"]),
                completed_jobs=completed,
                average_completion_seconds=(
                    total_completion / completed if completed else None
                ),
                first_submission_at=entry["first_submission"],
                last_submission_at=entry["last_submission"],
            )

        window_payload: dict[str, RenderWindowAnalytics] = {}
        for label, window in self.DEFAULT_SUBMISSION_WINDOWS.items():
            cutoff = moment - window
            total = 0
            completed = 0
            total_completion = 0.0
            for record in records:
                if record.created_at < cutoff:
                    continue
                total += 1
                if record.completed_at is not None:
                    completed += 1
                    completion_seconds = (
                        record.completed_at - record.created_at
                    ).total_seconds()
                    total_completion += max(completion_seconds, 0.0)
            window_payload[label] = RenderWindowAnalytics(
                total_jobs=total,
                completed_jobs=completed,
                average_completion_seconds=(
                    total_completion / completed if completed else None
                ),
            )

        return RenderAnalyticsResponse(
            generated_at=moment,
            total_jobs=len(records),
            statuses=status_payload,
            adapters=adapter_payload,
            submission_windows=window_payload,
        )

    def _emit_event(
        self,
        event: str,
        record: _JobRecord,
        *,
        payload_override: Mapping[str, Any] | None = None,
    ) -> None:
        if not self._events:
            return
        payload = {
            "event": event,
            "job": record.snapshot().model_dump(mode="json"),
        }
        if payload_override:
            payload.update(payload_override)
        self._events.publish(payload)


JOB_EVENTS = EventBroadcaster(max_buffer=64)


@lru_cache
def get_render_service() -> (
    RenderSubmissionService
):  # pragma: no cover - runtime wiring
    store_path = os.environ.get(JOB_STORE_PATH_ENV)
    history_limit_value = os.environ.get(JOB_HISTORY_LIMIT_ENV)
    retention_hours_value = os.environ.get(JOB_RETENTION_HOURS_ENV)
    poll_interval_value = os.environ.get(JOB_STATUS_POLL_INTERVAL_ENV)
    persist_interval_value = os.environ.get(JOB_STORE_PERSIST_THROTTLE_ENV)

    retention: timedelta | None = None
    if retention_hours_value:
        try:
            hours = float(retention_hours_value)
        except ValueError:
            logger.warning(
                "render.job.retention.invalid",
                value=retention_hours_value,
                env=JOB_RETENTION_HOURS_ENV,
            )
        else:
            if hours <= 0:
                logger.warning(
                    "render.job.retention.ignored",
                    value=retention_hours_value,
                    env=JOB_RETENTION_HOURS_ENV,
                )
            else:
                retention = timedelta(hours=hours)

    job_store = JobStore(store_path, retention=retention) if store_path else None

    history_limit = None
    if history_limit_value:
        try:
            history_limit = int(history_limit_value)
        except ValueError:
            logger.warning(
                "render.job.history_limit.invalid",
                value=history_limit_value,
                env=JOB_HISTORY_LIMIT_ENV,
            )

    poll_interval_override: float | None = None
    if poll_interval_value is not None:
        try:
            poll_interval_override = float(poll_interval_value)
        except ValueError:
            logger.warning(
                "render.job.poll_interval.invalid",
                value=poll_interval_value,
                env=JOB_STATUS_POLL_INTERVAL_ENV,
            )
            poll_interval_override = None
        else:
            if poll_interval_override <= 0:
                logger.warning(
                    "render.job.poll_interval.disabled",
                    value=poll_interval_value,
                    env=JOB_STATUS_POLL_INTERVAL_ENV,
                )

    persist_interval_override: float | None = None
    if persist_interval_value is not None:
        try:
            persist_interval_override = float(persist_interval_value)
        except ValueError:
            logger.warning(
                "render.job.store_interval.invalid",
                value=persist_interval_value,
                env=JOB_STORE_PERSIST_THROTTLE_ENV,
            )
            persist_interval_override = None
        else:
            if persist_interval_override <= 0:
                logger.warning(
                    "render.job.store_interval.disabled",
                    value=persist_interval_value,
                    env=JOB_STORE_PERSIST_THROTTLE_ENV,
                )

    service = RenderSubmissionService(
        job_store=job_store,
        history_limit=history_limit,
        broadcaster=JOB_EVENTS,
        status_poll_interval=poll_interval_override,
        store_persist_interval=persist_interval_override,
    )

    RenderJobRequest.configure_farm_registry(service.adapter_keys)

    return service


def parse_render_job_request(
    payload: Mapping[str, Any] = Body(...),
    service: RenderSubmissionService = Depends(get_render_service),
) -> RenderJobRequest:
    """FastAPI dependency that validates render submissions with registry context."""

    registry = service.adapter_keys()
    try:
        return RenderJobRequest.model_validate(
            payload, context={"farm_registry": registry}
        )
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


app = FastAPI(title="OnePiece Render Service", version=TRAFALGAR_VERSION)
router = create_protected_router()


@app.on_event("startup")
async def start_render_status_poller() -> None:
    service = get_render_service()
    service.start_background_polling()


@app.on_event("shutdown")
async def stop_render_status_poller() -> None:
    service = get_render_service()
    await service.stop_background_polling()


@app.exception_handler(RenderSubmissionError)
async def render_submission_error_handler(
    request: Request, exc: RenderSubmissionError
) -> JSONResponse:
    """Map adapter errors to standardised JSON responses."""

    status_code = exc.status_code or 400
    error_detail = APIErrorDetail(
        code=exc.code,
        message=str(exc),
        hint=exc.hint,
        context=exc.context or None,
    )
    log = logger.error if status_code >= 500 else logger.warning
    log(
        "render.api.error",
        code=error_detail.code,
        message=error_detail.message,
        hint=error_detail.hint,
        context=error_detail.context,
        status=status_code,
        path=str(request.url.path),
    )
    return JSONResponse(
        status_code=status_code,
        content=APIErrorResponse(error=error_detail).model_dump(exclude_none=True),
    )


@app.middleware("http")
async def log_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    logger.info(
        "render.api.request.start", method=request.method, path=request.url.path
    )
    response = await call_next(request)
    logger.info(
        "render.api.request.complete",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    )
    return response


@router.get("/")  # type: ignore[misc]
def root(
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> Mapping[str, str]:
    return {"message": "OnePiece Render API is running"}


@router.get("/health")  # type: ignore[misc]
def health(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> Mapping[str, Any]:
    analytics = service.get_render_analytics()
    status_summary = {
        name: {
            "count": metrics.count,
            "active": metrics.active,
            "average_duration_seconds": metrics.durations.average_seconds,
        }
        for name, metrics in analytics.statuses.items()
    }
    recent_submissions = {
        window: window_metrics.total_jobs
        for window, window_metrics in analytics.submission_windows.items()
    }
    active_jobs = sum(metric.active for metric in analytics.statuses.values())
    return {
        "status": "ok",
        "render_history": service.get_metrics(),
        "render_summary": {
            "total_jobs": analytics.total_jobs,
            "active_jobs": active_jobs,
            "by_status": status_summary,
            "submission_windows": recent_submissions,
        },
    }


@router.get("/farms", response_model=FarmsResponse)  # type: ignore[misc]
def farms(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> FarmsResponse:
    entries = service.list_farms()
    return FarmsResponse(farms=entries)


@router.post("/jobs")  # type: ignore[misc]
async def create_job(
    http_request: Request,
    job_request: RenderJobRequest = Depends(parse_render_job_request),
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_SUBMIT)),
) -> JSONResponse:
    logger.info(
        "render.api.submit.start",
        dcc=job_request.dcc,
        scene=job_request.scene,
        frames=job_request.frames,
        output=job_request.output,
        farm=job_request.farm,
        priority=job_request.priority,
        user=job_request.user,
    )
    try:
        result = service.submit_job(job_request)
    except RenderSubmissionError as exc:
        return await render_submission_error_handler(http_request, exc)
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.exception(
            "render.api.submit.error",
            farm=job_request.farm,
            scene=job_request.scene,
        )
        raise HTTPException(
            status_code=500,
            detail="Unexpected error while submitting render job.",
        ) from exc

    payload = RenderJobResponse(
        job_id=result.get("job_id", ""),
        status=result.get("status", "unknown"),
        farm_type=result.get("farm_type", job_request.farm),
        message=result.get("message"),
    )

    logger.info(
        "render.api.submit.complete",
        farm=payload.farm_type,
        status=payload.status,
        job_id=payload.job_id,
    )

    return JSONResponse(status_code=201, content=payload.model_dump())


@router.get("/jobs", response_model=JobsListResponse)  # type: ignore[misc]
def list_jobs(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
    limit: int | None = Query(
        None,
        gt=0,
        description="Maximum number of jobs to return.",
    ),
    status: list[str] | None = Query(
        None,
        description="Filter by one or more job status values.",
    ),
    farm: list[str] | None = Query(
        None,
        description="Filter by one or more farm identifiers.",
    ),
) -> JobsListResponse:
    jobs = service.list_jobs(limit=limit, status=status, farm=farm)
    return JobsListResponse(jobs=jobs)


@router.get("/jobs/metrics", response_model=RenderAnalyticsResponse)  # type: ignore[misc]
def job_metrics(
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> RenderAnalyticsResponse:
    return service.get_render_analytics()


def _format_sse_chunk(event_name: str | None, payload: bytes) -> bytes:
    lines: list[bytes] = []
    if event_name:
        lines.append(b"event: " + event_name.encode("utf-8"))
    lines.append(b"data: " + payload)
    return b"\n".join(lines) + b"\n\n"


async def _job_event_stream(request: Request) -> AsyncGenerator[bytes, Any]:
    service = get_render_service()
    queue = await JOB_EVENTS.subscribe()
    try:
        jobs_snapshot = [job.model_dump(mode="json") for job in service.list_jobs()]
        snapshot_event = {"event": "jobs.snapshot", "jobs": jobs_snapshot}
        snapshot_payload = json.dumps(snapshot_event).encode("utf-8")
        yield _format_sse_chunk("jobs.snapshot", snapshot_payload)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                if await request.is_disconnected():
                    break
                yield _format_sse_chunk(None, b"{}")
                continue
            payload = json.dumps(event).encode("utf-8")
            event_name = event.get("event") if isinstance(event, Mapping) else None
            chunk = _format_sse_chunk(
                event_name if isinstance(event_name, str) else None, payload
            )
            yield chunk
    finally:
        await JOB_EVENTS.unsubscribe(queue)


@router.get("/jobs/stream")  # type: ignore[misc]
async def stream_jobs(
    request: Request,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> StreamingResponse:
    return StreamingResponse(_job_event_stream(request), media_type="text/event-stream")


@router.websocket("/jobs/ws")  # type: ignore[misc]
async def jobs_websocket(
    websocket: WebSocket,
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
    service: RenderSubmissionService = Depends(get_render_service),
) -> None:
    await websocket.accept()
    queue = await JOB_EVENTS.subscribe()
    try:
        jobs_snapshot = [job.model_dump(mode="json") for job in service.list_jobs()]
        handshake: dict[str, Any] = {
            "type": "connected",
            "snapshot": {"event": "jobs.snapshot", "jobs": jobs_snapshot},
        }
        await websocket.send_json(handshake)

        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        await JOB_EVENTS.unsubscribe(queue)


@router.get("/jobs/{job_id}", response_model=RenderJobMetadata)  # type: ignore[misc]
def get_job(
    job_id: str,
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_READ)),
) -> RenderJobMetadata:
    try:
        return service.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


@router.delete("/jobs/{job_id}", response_model=RenderJobMetadata)  # type: ignore[misc]
def cancel_job(
    job_id: str,
    service: RenderSubmissionService = Depends(get_render_service),
    _principal: AuthenticatedPrincipal = Depends(require_roles(ROLE_RENDER_MANAGE)),
) -> RenderJobMetadata:
    try:
        return service.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Job not found.") from exc


app.include_router(router)
