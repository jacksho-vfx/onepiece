"""FastAPI application exposing render job submission endpoints."""

from __future__ import annotations

import asyncio
import getpass
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Awaitable,
    Callable,
    Mapping,
    Collection,
    ClassVar,
)

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from apps.onepiece.render.submit import (
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
from libraries.automation.render.base import (
    AdapterCapabilities,
    RenderAdapterUnavailableError,
    RenderSubmissionError,
    SubmissionResult,
)
from libraries.automation.render.models import CapabilityProvider, RenderAdapter

from apps.trafalgar.web.events import EventBroadcaster
from apps.trafalgar.web.job_store import JobStore
from apps.trafalgar.web.security import (
    AuthenticatedPrincipal,
    ROLE_RENDER_MANAGE,
    ROLE_RENDER_READ,
    ROLE_RENDER_SUBMIT,
)
from .schemas import (
    APIErrorDetail,
    APIErrorResponse,
    CancellationCapabilityDescriptor,
    ChunkingCapabilityDescriptor,
    DurationMetrics,
    FarmCapabilities,
    FarmInfo,
    FarmsResponse,
    JobsListResponse,
    PriorityCapabilityDescriptor,
    RenderAdapterAnalytics,
    RenderAnalyticsResponse,
    RenderJobMetadata,
    RenderJobRequest,
    RenderJobResponse,
    RenderStatusAnalytics,
    RenderWindowAnalytics,
)

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialise_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime:
    """Parse ``value`` into a timezone-aware UTC timestamp."""

    timestamp: datetime | None = None

    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, (int, float)):
        try:
            timestamp = datetime.fromtimestamp(value, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(f"Unsupported timestamp value: {value!r}") from exc
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("Timestamp strings cannot be empty.")
        if text.endswith(("Z", "z")):
            text = f"{text[:-1]}+00:00"
        try:
            timestamp = datetime.fromisoformat(text)
        except ValueError:
            try:
                numeric = float(text)
            except ValueError as float_exc:
                raise ValueError(
                    f"Unsupported timestamp value: {value!r}"
                ) from float_exc
            try:
                timestamp = datetime.fromtimestamp(numeric, tz=timezone.utc)
            except (OverflowError, OSError, ValueError) as ts_exc:
                raise ValueError(f"Unsupported timestamp value: {value!r}") from ts_exc
    else:
        raise ValueError(f"Unsupported timestamp value: {value!r}")

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


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


def _build_farm_capabilities(
    farm: str,
    capabilities: AdapterCapabilities | None,
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
        try:
            created_at = _parse_timestamp(created_at_raw)
        except ValueError as exc:
            raise ValueError(
                "Stored job record has an invalid created_at timestamp."
            ) from exc
        updated_at_raw = payload.get("updated_at")
        if updated_at_raw:
            try:
                updated_at = _parse_timestamp(updated_at_raw)
            except ValueError:
                updated_at = created_at
        else:
            updated_at = created_at
        completed_at_raw = payload.get("completed_at")
        if completed_at_raw is not None:
            try:
                completed_at = _parse_timestamp(completed_at_raw)
            except ValueError:
                completed_at = None
        else:
            completed_at = None
        history_payload = payload.get("status_history") or []
        history: list[tuple[str, datetime]] = []
        for entry in history_payload:
            if not isinstance(entry, Mapping):
                continue
            status_value = str(entry.get("status", payload.get("status", "unknown")))
            timestamp_raw = entry.get("timestamp")
            if timestamp_raw is None:
                timestamp = created_at
            else:
                try:
                    timestamp = _parse_timestamp(timestamp_raw)
                except ValueError:
                    continue
            history.append((status_value, timestamp))
        if not history:
            history.append((str(payload.get("status", "unknown")), created_at))
        request_payload = payload.get("request")
        if not isinstance(request_payload, Mapping):
            raise ValueError("Stored job request payload must be a mapping.")
        persisted_farm = request_payload.get("farm") or payload.get("farm")
        context: dict[str, Collection[str]] | None = None
        if persisted_farm is not None:
            farm_key = str(persisted_farm).strip().lower()
            if farm_key:
                context = {"farm_registry": {farm_key}}
        if context is None:
            request = RenderJobRequest.model_validate(request_payload)
        else:
            request = RenderJobRequest.model_validate(request_payload, context=context)

        return cls(
            job_id=str(payload["job_id"]),
            farm=str(payload["farm"]),
            farm_type=str(payload.get("farm_type", payload["farm"])),
            status=str(payload.get("status", "unknown")),
            message=payload.get("message"),
            request=request,
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
            status_history=history,
        )


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
        self._lock = threading.RLock()
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
        else:
            self._capability_sources.pop(key, None)

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
            resolved_priority, resolved_chunk, _, _ = _resolve_priority_and_chunk_size(
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
        raw_job_id = result.get("job_id")
        job_id: str = ""
        if raw_job_id is not None:
            if isinstance(raw_job_id, bytes):
                if raw_job_id:
                    job_id = raw_job_id.decode("utf-8", errors="replace")
            else:
                text = str(raw_job_id)
                if text:
                    job_id = text
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
            with self._lock:
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

        with self._lock:
            job_ids = list(reversed(self._jobs.keys()))

        jobs: list[RenderJobMetadata] = []
        dirty = False
        for job_id in job_ids:
            if limit is not None and len(jobs) >= limit:
                break

            with self._lock:
                record = self._jobs.get(job_id)
            if record is None:
                continue

            dirty = self._refresh_job(record) or dirty

            with self._lock:
                current = self._jobs.get(job_id)
                if current is None:
                    continue

                if status_filter is not None:
                    record_status = (current.status or "").strip().lower()
                    if record_status not in status_filter:
                        continue

                if farm_filter is not None:
                    record_farm = (current.farm or "").strip().lower()
                    if record_farm not in farm_filter:
                        continue

                snapshot = current.snapshot()

            jobs.append(snapshot)

        if dirty:
            self._persist_jobs(force=True)
        return jobs

    def get_job(self, job_id: str) -> RenderJobMetadata:
        with self._lock:
            record = self._jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        if self._refresh_job(record):
            self._persist_jobs(force=True)
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                raise KeyError(job_id)
            return current.snapshot()

    def cancel_job(self, job_id: str) -> RenderJobMetadata:
        with self._lock:
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
        with self._lock:
            changed = self._update_record_from_result(record, result)
        if changed:
            self._persist_jobs(force=True)
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                raise KeyError(job_id)
            return current.snapshot()

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
        with self._lock:
            current = self._jobs.get(record.job_id)
            if current is None:
                return False
            return self._update_record_from_result(current, result)

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
        with self._lock:
            self._jobs = OrderedDict(
                (record.job_id, record) for record in loaded_records
            )
            previous_count = len(self._jobs)
            self._enforce_history_limit()
            history_limit = self._history_limit
            current_count = len(self._jobs)
        if history_limit is not None and current_count < previous_count:
            self._persist_jobs(force=True)

    def _persist_jobs(self, *, force: bool = False) -> None:
        store = self._store
        if not store:
            with self._lock:
                self._persist_pending = False
            return
        now = _utcnow()
        with self._lock:
            if (
                not force
                and self._persist_throttle is not None
                and self._last_persist_at is not None
                and now - self._last_persist_at < self._persist_throttle
            ):
                self._persist_pending = True
                return
            records = list(self._jobs.values())
        store.save(records)
        with self._lock:
            self._last_persist_at = now
            self._persist_pending = False

    def _enforce_history_limit(self) -> None:
        with self._lock:
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
                with self._lock:
                    records = list(self._jobs.values())
                dirty = False
                for record in records:
                    dirty = self._refresh_job(record) or dirty
                with self._lock:
                    persist_pending = self._persist_pending
                if dirty or persist_pending:
                    self._persist_jobs()
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            raise
        finally:
            with self._lock:
                pending = self._persist_pending
            if pending:
                self._persist_jobs(force=True)

    def get_metrics(self) -> dict[str, Any]:
        store_metrics: dict[str, Any] | None = None
        if self._store:
            store_metrics = self._store.stats.to_dict()
        with self._lock:
            history_size = len(self._jobs)
            history_limit = self._history_limit
            history_pruned_total = self._history_pruned_total
            last_history_prune_at = self._last_history_prune_at
            last_history_prune_count = self._last_history_prune_count
        return {
            "history_size": history_size,
            "history_limit": history_limit,
            "history_pruned_total": history_pruned_total,
            "last_history_prune_at": _serialise_datetime(last_history_prune_at),
            "last_history_pruned": last_history_prune_count,
            "store": store_metrics,
        }

    def get_render_analytics(
        self, *, now: datetime | None = None
    ) -> RenderAnalyticsResponse:
        """Compute aggregated analytics for render job history."""

        moment = now or _utcnow()
        with self._lock:
            records = list(self._jobs.values())

            status_totals: dict[str, dict[str, Any]] = {}
            adapter_totals: dict[str, Any] = {}

            def normalise_status(value: str | None) -> str:
                if value is None:
                    return "unknown"
                text = str(value).strip().lower()
                return text or "unknown"

            for record in records:
                record_updated = record.updated_at or record.created_at
                durations = record.status_durations(now=moment)
                for status_name, duration_seconds in durations.items():
                    status_key = normalise_status(status_name)
                    status_entry = status_totals.setdefault(
                        status_key,
                        {
                            "jobs": set(),
                            "total_duration": 0.0,
                            "active": 0,
                            "last_updated": None,
                        },
                    )
                    # Track job identifiers per status so we can report the number of
                    # distinct jobs that have visited the status rather than the number
                    # of status transitions recorded in history.
                    status_entry["jobs"].add(record.job_id)
                    status_entry["total_duration"] += max(duration_seconds, 0.0)
                    if record_updated is not None:
                        last_updated: datetime | None = status_entry["last_updated"]
                        if last_updated is None or record_updated > last_updated:
                            status_entry["last_updated"] = record_updated

                record_status = normalise_status(record.status)
                status_entry = status_totals.setdefault(
                    record_status,
                    {
                        "jobs": set(),
                        "total_duration": 0.0,
                        "active": 0,
                        "last_updated": None,
                    },
                )
                status_entry["active"] += 1
                status_entry["jobs"].add(record.job_id)
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
                adapter_entry["statuses"][record_status] += 1

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
                count = len(entry["jobs"])
                active = entry["active"]
                total_duration = entry["total_duration"]
                effective_count = count or active
                average = (
                    (total_duration / effective_count) if effective_count else None
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

            response = RenderAnalyticsResponse(
                generated_at=moment,
                total_jobs=len(records),
                statuses=status_payload,
                adapters=adapter_payload,
                submission_windows=window_payload,
            )
        return response

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


app = FastAPI(title="OnePiece Render Service", version=TRAFALGAR_VERSION)


from . import dependencies as _dependencies  # noqa: E402
from . import routes as _routes  # noqa: E402
from .streaming import RENDER_SSE_KEEPALIVE_INTERVAL_ENV as _KEEPALIVE_ENV  # noqa: E402

get_render_service = _dependencies.get_render_service
parse_render_job_request = _dependencies.parse_render_job_request
start_render_status_poller = _dependencies.start_render_status_poller
stop_render_status_poller = _dependencies.stop_render_status_poller
JOB_STORE_PATH_ENV = _dependencies.JOB_STORE_PATH_ENV
JOB_HISTORY_LIMIT_ENV = _dependencies.JOB_HISTORY_LIMIT_ENV
JOB_RETENTION_HOURS_ENV = _dependencies.JOB_RETENTION_HOURS_ENV
JOB_STATUS_POLL_INTERVAL_ENV = _dependencies.JOB_STATUS_POLL_INTERVAL_ENV
JOB_STORE_PERSIST_THROTTLE_ENV = _dependencies.JOB_STORE_PERSIST_THROTTLE_ENV
RENDER_SSE_KEEPALIVE_INTERVAL_ENV = _KEEPALIVE_ENV

router = _routes.router

app.add_event_handler("startup", start_render_status_poller)
app.add_event_handler("shutdown", stop_render_status_poller)
app.add_exception_handler(RenderSubmissionError, render_submission_error_handler)
app.middleware("http")(log_requests)
app.include_router(router)


__all__ = [
    "RenderSubmissionService",
    "RenderJobRequest",
    "RenderJobResponse",
    "RenderJobMetadata",
    "RenderAnalyticsResponse",
    "RenderAdapterAnalytics",
    "RenderStatusAnalytics",
    "RenderWindowAnalytics",
    "JobsListResponse",
    "FarmsResponse",
    "FarmInfo",
    "FarmCapabilities",
    "_JobRecord",
    "JOB_EVENTS",
    "JOB_STORE_PATH_ENV",
    "JOB_HISTORY_LIMIT_ENV",
    "JOB_RETENTION_HOURS_ENV",
    "JOB_STATUS_POLL_INTERVAL_ENV",
    "JOB_STORE_PERSIST_THROTTLE_ENV",
    "RENDER_SSE_KEEPALIVE_INTERVAL_ENV",
    "AuthenticatedPrincipal",
    "ROLE_RENDER_MANAGE",
    "ROLE_RENDER_READ",
    "ROLE_RENDER_SUBMIT",
    "RenderSubmissionError",
    "get_render_service",
    "parse_render_job_request",
    "start_render_status_poller",
    "stop_render_status_poller",
    "render_submission_error_handler",
    "log_requests",
    "app",
    "router",
]
