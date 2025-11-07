"""Core services for render job submission and tracking."""

from __future__ import annotations

import asyncio
import getpass
import threading
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from typing import Any, ClassVar, Collection, Mapping

import structlog

from apps.onepiece.render.submit import (
    FARM_ADAPTERS,
    FARM_CAPABILITY_PROVIDERS,
    resolve_priority_and_chunk_size,
)
from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceValidationError,
)
from apps.trafalgar.web.events import EventBroadcaster
from apps.trafalgar.web.job_store import JobStore
from libraries.automation.render.base import (
    AdapterCapabilities,
    RenderAdapterUnavailableError,
    RenderSubmissionError,
    SubmissionResult,
)
from libraries.automation.render.models import CapabilityProvider, RenderAdapter

from .api import build_farm_capabilities
from .models import (
    TERMINAL_STATUSES,
    _JobRecord,
    _serialise_datetime,
    _utcnow,
)
from .schemas import (
    DurationMetrics,
    FarmInfo,
    RenderAdapterAnalytics,
    RenderAnalyticsResponse,
    RenderJobMetadata,
    RenderJobRequest,
    RenderStatusAnalytics,
    RenderWindowAnalytics,
)

logger = structlog.get_logger(__name__)

FARM_DESCRIPTIONS: Mapping[str, str] = {
    "deadline": "Autodesk Deadline render manager (stub).",
    "tractor": "Pixar Tractor render farm (stub).",
    "opencue": "OpenCue render manager (stub).",
    "mock": "Mock render farm for testing and demos.",
}

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
            capabilities = build_farm_capabilities(name, capability_data)
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
            resolved_priority, resolved_chunk, _, _ = resolve_priority_and_chunk_size(
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
                status_code=503,
                hint="The render farm is currently unavailable. Try again later.",
                context={"farm": request.farm},
            ) from exc

        try:
            result = adapter(
                scene=request.scene,
                frames=request.frames,
                output=request.output,
                dcc=request.dcc,
                priority=resolved_priority,
                user=resolved_user,
                chunk_size=resolved_chunk,
            )
        except RenderAdapterUnavailableError as exc:
            raise RenderSubmissionError(
                str(exc),
                code="render.adapter_unavailable",
                status_code=503,
                hint="The render adapter is temporarily unavailable. Try again later.",
                context={"farm": request.farm},
            ) from exc
        except RenderSubmissionError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            raise RenderSubmissionError(
                "An unexpected error occurred during submission.",
                code="render.submit_failed",
                status_code=500,
                hint="Review the render job request and retry. If the problem persists contact support.",
                context={"farm": request.farm},
            ) from exc

        raw_job_id = result.get("job_id")
        job_id = ""
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
                self._history_pruned_total += removed
                self._last_history_prune_count = removed

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
            adapter_totals: dict[str, dict[str, Any]] = {}

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


__all__ = [
    "DEFAULT_STATUS_POLL_INTERVAL",
    "DEFAULT_STORE_PERSIST_INTERVAL",
    "FARM_DESCRIPTIONS",
    "RenderSubmissionService",
    "logger",
]
