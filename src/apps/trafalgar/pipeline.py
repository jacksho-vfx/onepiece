"""Pipeline orchestration helpers shared across Trafalgar services."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, AsyncIterator, Iterable, Iterator, Mapping, cast

import json
import sqlite3
import uuid

from apps.onepiece.config import ProfileContext
from apps.trafalgar.providers import pipeline_executor
from libraries.pipeline.factories import pipeline_from_config
from libraries.pipeline.models import Pipeline, PipelineStep


PROVIDER_REFERENCE_METADATA_KEY = pipeline_executor.PROVIDER_REFERENCE_METADATA_KEY


@dataclass(slots=True)
class PipelineDefinition:
    """A lightweight description of a runnable pipeline."""

    name: str
    pipeline: Pipeline
    display_name: str | None = None
    description: str | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        if not self.name:
            msg = "pipeline definitions require a name"
            raise ValueError(msg)
        if not isinstance(self.pipeline, Pipeline):
            msg = "pipeline definitions require a Pipeline instance"
            raise TypeError(msg)
        if self.parameters is None:
            object.__setattr__(self, "parameters", {})
        else:
            object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        steps = [self._serialise_step(step) for step in self.pipeline.steps]
        providers = {step["name"]: step["provider"] for step in steps}
        dependency_graph = {
            step["name"]: step["trigger"]["depends_on"] for step in steps
        }

        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "parameters": dict(self.parameters),
            "metadata": dict(self.pipeline.metadata),
            "steps": steps,
            "providers": providers,
            "dependency_graph": dependency_graph,
        }

    def _serialise_step(self, step: PipelineStep) -> Mapping[str, Any]:
        trigger = step.trigger
        metadata = dict(step.metadata)
        provider_reference = metadata.pop(PROVIDER_REFERENCE_METADATA_KEY, None)
        return {
            "name": step.name,
            "provider": (
                provider_reference
                if provider_reference is not None
                else self._serialise_provider(step.provider)
            ),
            "config": dict(step.config),
            "metadata": metadata,
            "trigger": {
                "kind": trigger.kind,
                "depends_on": list(trigger.depends_on),
                "event": trigger.event,
                "filters": dict(trigger.filters),
            },
        }

    @staticmethod
    def _serialise_provider(provider: Any) -> str:
        if isinstance(provider, str):
            return provider

        module = getattr(provider, "__module__", None)
        qualname = getattr(provider, "__qualname__", None)
        if module and qualname:
            return f"{module}:{qualname}"

        name = getattr(provider, "__name__", None)
        if module and name:
            return f"{module}:{name}"

        return repr(provider)


@dataclass(slots=True)
class PipelineRun:
    """Metadata describing a pipeline run returned by the orchestrator."""

    run_id: str
    pipeline: str
    status: str
    created_at: datetime
    updated_at: datetime
    parameters: Mapping[str, Any] = field(default_factory=dict)
    definition_snapshot: Mapping[str, Any] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))
        object.__setattr__(self, "definition_snapshot", dict(self.definition_snapshot))
        if self.metrics is None:
            object.__setattr__(self, "metrics", {})
        else:
            object.__setattr__(self, "metrics", dict(self.metrics))

    def serialise(self) -> Mapping[str, Any]:
        timing: dict[str, Any] = {
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
        }

        totals = (
            self.metrics.get("totals", {}) if isinstance(self.metrics, dict) else {}
        )
        if "step_duration_ms" in totals:
            timing["total_step_duration_ms"] = totals.get("step_duration_ms")

        steps_payload: dict[str, Any] = {}
        if isinstance(self.metrics, dict):
            steps = self.metrics.get("steps", {})
            if isinstance(steps, dict):
                for name, details in steps.items():
                    if not isinstance(details, dict):
                        continue
                    count = details.get("count", 0)
                    total_duration: int = details.get("total_duration_ms")  # type: ignore[assignment]
                    try:
                        total_duration_value = int(total_duration)
                    except (TypeError, ValueError):
                        total_duration_value = None
                    average: float | None
                    if count and total_duration_value is not None:
                        average = total_duration_value / count
                    else:
                        average = None
                    steps_payload[name] = {
                        "count": count,
                        "total_duration_ms": total_duration_value,
                        "average_duration_ms": average,
                        "last_started_at": details.get("last_started_at"),
                        "last_finished_at": details.get("last_finished_at"),
                        "last_duration_ms": details.get("last_duration_ms"),
                    }

        return {
            "id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "parameters": dict(self.parameters),
            "definition_snapshot": dict(self.definition_snapshot),
            "timing": timing,
            "step_metrics": steps_payload,
        }


@dataclass(slots=True)
class PipelineRunEvent:
    """A single status update emitted for a pipeline run."""

    run_id: str
    pipeline: str
    status: str
    timestamp: datetime
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        return {
            "id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "parameters": dict(self.parameters),
        }


@dataclass(slots=True)
class _RunEventSubscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[PipelineRunEvent]


@dataclass(frozen=True, slots=True)
class PipelineRetentionPolicy:
    """Constraints applied when pruning historical pipeline runs."""

    max_age: timedelta | None = None
    max_runs: int | None = None

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        if self.max_age is not None and self.max_age.total_seconds() < 0:
            msg = "retention max_age must be non-negative"
            raise ValueError(msg)
        if self.max_runs is not None and self.max_runs < 0:
            msg = "retention max_runs must be non-negative"
            raise ValueError(msg)

    @property
    def configured(self) -> bool:
        return self.max_age is not None or self.max_runs is not None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> PipelineRetentionPolicy | None:
        """Construct a retention policy from a configuration mapping."""

        if not payload:
            return None

        if not isinstance(payload, Mapping):  # pragma: no cover - defensive guard
            msg = "retention configuration must be a mapping"
            raise TypeError(msg)

        max_runs_raw = payload.get("max_runs")
        max_runs: int | None
        if max_runs_raw is None:
            max_runs = None
        else:
            try:
                max_runs = int(max_runs_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("retention max_runs must be an integer") from exc
            if max_runs < 0:
                raise ValueError("retention max_runs must be non-negative")

        duration_keys = {
            "seconds": 1,
            "minutes": 60,
            "hours": 3600,
            "days": 86400,
        }
        window_seconds: float | None = None
        for key, multiplier in duration_keys.items():
            if key not in payload:
                continue
            if window_seconds is not None:
                msg = "only one of seconds/minutes/hours/days may be provided"
                raise ValueError(msg)
            raw_value = payload[key]
            try:
                window_seconds = float(raw_value) * multiplier
            except (TypeError, ValueError) as exc:
                raise ValueError(f"retention {key} value must be numeric") from exc
        max_age: timedelta | None
        if window_seconds is None:
            max_age = None
        else:
            if window_seconds < 0:
                raise ValueError("retention duration must be non-negative")
            max_age = timedelta(seconds=window_seconds)

        policy = cls(max_age=max_age, max_runs=max_runs)
        if not policy.configured:
            return None
        return policy


@dataclass(slots=True)
class PipelinePruneResult:
    """Outcome generated after pruning pipeline run history."""

    removed_runs: int
    removed_events: int
    remaining_runs: int
    max_age: timedelta | None = None
    max_runs: int | None = None

    def serialise(self) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "removed_runs": self.removed_runs,
            "removed_events": self.removed_events,
            "remaining_runs": self.remaining_runs,
            "max_runs": self.max_runs,
        }
        payload["max_age_seconds"] = (
            int(self.max_age.total_seconds()) if self.max_age is not None else None
        )
        return payload


class PipelineRunStore:
    """SQLite backed persistence layer for pipeline runs and events."""

    DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        *,
        database: str | Path | None = None,
        busy_timeout: float | int | None = None,
    ) -> None:
        if database is None:
            database_path = ":memory:"
            self._path: Path | None = None
        else:
            database_str = str(database)
            if database_str == ":memory:":
                database_path = ":memory:"
                self._path = None
            else:
                path = Path(database)
                path.parent.mkdir(parents=True, exist_ok=True)
                database_path = str(path)
                self._path = path

        self._lock = Lock()
        busy_timeout_ms = self._coerce_busy_timeout_ms(busy_timeout)
        self._connection = sqlite3.connect(
            database_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self._busy_timeout_ms = busy_timeout_ms
        self._initialise_schema()
        self._subscribers: dict[str, list[_RunEventSubscriber]] = {}
        self._closed = False

    def close(self) -> None:
        """Release any database resources held by the store."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscribers = self._subscribers
            self._subscribers = {}
            connection = self._connection

        try:
            connection.close()
        finally:
            subscribers.clear()

    @classmethod
    def _coerce_busy_timeout_ms(cls, value: float | int | None) -> int:
        if value is None:
            seconds = cls.DEFAULT_BUSY_TIMEOUT_SECONDS
        else:
            try:
                seconds = float(value)
            except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                raise ValueError("busy_timeout must be a number") from exc
        if seconds < 0:
            msg = "busy_timeout must be non-negative"
            raise ValueError(msg)
        return int(seconds * 1000)

    @staticmethod
    def _encode_datetime(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _decode_datetime(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _encode_parameters(parameters: Mapping[str, Any]) -> str:
        def _default(value: Any) -> Any:
            return str(value)

        return json.dumps(dict(parameters), default=_default)

    @staticmethod
    def _decode_parameters(payload: str) -> dict[str, Any]:
        if not payload:
            return {}
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _encode_definition_snapshot(snapshot: Mapping[str, Any]) -> str:
        return json.dumps(dict(snapshot))

    @staticmethod
    def _decode_definition_snapshot(payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _encode_optional_datetime(value: datetime | None) -> str | None:
        if value is None:
            return None
        return PipelineRunStore._encode_datetime(value)

    @staticmethod
    def _decode_optional_datetime(value: str | None) -> datetime | None:
        if value is None:
            return None
        return PipelineRunStore._decode_datetime(value)

    @staticmethod
    def _encode_metrics(metrics: Mapping[str, Any]) -> str:
        return json.dumps(dict(metrics))

    @staticmethod
    def _decode_metrics(payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        data = json.loads(payload)
        if isinstance(data, dict):
            return data
        return {}

    @staticmethod
    def _initial_metrics() -> dict[str, Any]:
        return {"steps": {}, "totals": {"step_duration_ms": 0}}

    @staticmethod
    def _normalise_metrics(metrics: Mapping[str, Any] | None) -> dict[str, Any]:
        if isinstance(metrics, dict):
            steps_source = metrics.get("steps", {})
            totals_source = metrics.get("totals", {})
        else:
            steps_source = {}
            totals_source = {}
        steps: dict[str, dict[str, Any]] = {}
        if isinstance(steps_source, dict):
            for name, details in steps_source.items():
                if isinstance(details, dict):
                    steps[name] = dict(details)
        totals: dict[str, Any]
        if isinstance(metrics, dict) and isinstance(totals_source, dict):
            totals = dict(totals_source)
        else:
            totals = {}
        if "step_duration_ms" not in totals:
            total_duration = 0
            for data in steps.values():
                value: int = data.get("total_duration_ms")  # type: ignore[assignment]
                try:
                    total_duration += int(value)
                except (TypeError, ValueError):
                    continue
            totals["step_duration_ms"] = total_duration
        return {"steps": steps, "totals": totals}

    def _apply_event_metrics(
        self,
        *,
        metrics: dict[str, Any],
        status: str,
        timestamp: datetime,
        parameters: Mapping[str, Any],
        run_status: str | None,
        created_at: datetime,
        started_at: datetime | None,
        finished_at: datetime | None,
        duration_ms: int | None,
    ) -> tuple[dict[str, Any], datetime | None, datetime | None, int | None]:
        steps = metrics.setdefault("steps", {})
        totals = metrics.setdefault("totals", {})
        if not isinstance(steps, dict):
            steps = {}
            metrics["steps"] = steps
        if not isinstance(totals, dict):
            totals = {}
            metrics["totals"] = totals
        totals.setdefault("step_duration_ms", 0)

        step_name = parameters.get("step")
        duration_value = parameters.get("duration_ms")
        started_value = parameters.get("started_at")
        finished_value = parameters.get("finished_at")

        duration_int: int | None
        try:
            duration_int = int(duration_value) if duration_value is not None else None
        except (TypeError, ValueError):
            duration_int = None

        if isinstance(step_name, str) and duration_int is not None:
            existing = steps.get(step_name)
            if not isinstance(existing, dict):
                existing = {}
            count_value = existing.get("count", 0)
            try:
                count = int(count_value)
            except (TypeError, ValueError):
                count = 0
            total_value = existing.get("total_duration_ms", 0)
            try:
                total_duration_ms = int(total_value)
            except (TypeError, ValueError):
                total_duration_ms = 0
            existing.update(
                {
                    "count": count + 1,
                    "total_duration_ms": total_duration_ms + duration_int,
                    "last_started_at": started_value,
                    "last_finished_at": finished_value,
                    "last_duration_ms": duration_int,
                }
            )
            steps[step_name] = existing

            total_steps_value = totals.get("step_duration_ms", 0)
            try:
                total_steps_duration = int(total_steps_value)
            except (TypeError, ValueError):
                total_steps_duration = 0
            totals["step_duration_ms"] = total_steps_duration + duration_int

        current_started = started_at
        current_finished = finished_at
        current_duration = duration_ms

        if run_status == "running" and current_started is None:
            current_started = timestamp
        if run_status in {"succeeded", "failed"}:
            current_finished = timestamp
            anchor = current_started or created_at
            if anchor is not None:
                delta = current_finished - anchor
                computed = int(max(delta.total_seconds() * 1000, 0))
                current_duration = computed

        return metrics, current_started, current_finished, current_duration

    def _initialise_schema(self) -> None:
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    pipeline TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    definition_snapshot TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    metrics TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pipeline_run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    pipeline TEXT NOT NULL,
                    status TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES pipeline_runs(run_id)
                )
                """
            )

        self._ensure_pipeline_runs_columns()

    def _ensure_pipeline_runs_columns(self) -> None:
        cursor = self._connection.execute("PRAGMA table_info(pipeline_runs)")
        columns = {row[1] for row in cursor.fetchall()}
        if "definition_snapshot" not in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN definition_snapshot TEXT NOT NULL DEFAULT '{}'"
                )
        if "started_at" not in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN started_at TEXT"
                )
        if "finished_at" not in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN finished_at TEXT"
                )
        if "duration_ms" not in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN duration_ms INTEGER"
                )
        if "metrics" not in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN metrics TEXT NOT NULL DEFAULT '{}'"
                )
                self._connection.execute(
                    "UPDATE pipeline_runs SET metrics = '{}' WHERE metrics IS NULL"
                )

    def create_run(self, run: PipelineRun, initial_event: PipelineRunEvent) -> None:
        payload = self._encode_parameters(run.parameters)
        definition_payload = self._encode_definition_snapshot(run.definition_snapshot)
        event_payload = self._encode_parameters(initial_event.parameters)
        metrics = self._normalise_metrics(run.metrics)
        metrics_payload = self._encode_metrics(metrics)
        encoded_started_at = self._encode_optional_datetime(run.started_at)
        encoded_finished_at = self._encode_optional_datetime(run.finished_at)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO pipeline_runs (
                    run_id, pipeline, status, created_at, updated_at, parameters,
                    definition_snapshot, started_at, finished_at, duration_ms, metrics
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.pipeline,
                    run.status,
                    self._encode_datetime(run.created_at),
                    self._encode_datetime(run.updated_at),
                    payload,
                    definition_payload,
                    encoded_started_at,
                    encoded_finished_at,
                    run.duration_ms,
                    metrics_payload,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO pipeline_run_events (
                    run_id, pipeline, status, timestamp, parameters
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    initial_event.run_id,
                    initial_event.pipeline,
                    initial_event.status,
                    self._encode_datetime(initial_event.timestamp),
                    event_payload,
                ),
            )

    def append_event(
        self,
        run_id: str,
        *,
        status: str,
        timestamp: datetime,
        parameters: Mapping[str, Any],
        run_status: str | None,
    ) -> None:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT pipeline, created_at, metrics, started_at, finished_at,
                       duration_ms
                FROM pipeline_runs
                WHERE run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
            if row is None:
                msg = f"run '{run_id}' could not be found"
                raise KeyError(msg)
            pipeline = row["pipeline"]
            created_at = self._decode_datetime(row["created_at"])
            metrics = self._normalise_metrics(self._decode_metrics(row["metrics"]))
            started_at = self._decode_optional_datetime(row["started_at"])
            finished_at = self._decode_optional_datetime(row["finished_at"])
            duration_ms = row["duration_ms"]
            encoded_parameters = self._encode_parameters(parameters)
            encoded_timestamp = self._encode_datetime(timestamp)

            metrics, started_at, finished_at, duration_ms = self._apply_event_metrics(
                metrics=metrics,
                status=status,
                timestamp=timestamp,
                parameters=parameters,
                run_status=run_status,
                created_at=created_at,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
            )
            encoded_metrics = self._encode_metrics(metrics)
            encoded_started_at = self._encode_optional_datetime(started_at)
            encoded_finished_at = self._encode_optional_datetime(finished_at)

            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO pipeline_run_events (
                        run_id, pipeline, status, timestamp, parameters
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        pipeline,
                        status,
                        encoded_timestamp,
                        encoded_parameters,
                    ),
                )
                if run_status is not None:
                    self._connection.execute(
                        """
                        UPDATE pipeline_runs
                        SET status = ?, updated_at = ?, started_at = ?,
                            finished_at = ?, duration_ms = ?, metrics = ?
                        WHERE run_id = ?
                        """,
                        (
                            run_status,
                            encoded_timestamp,
                            encoded_started_at,
                            encoded_finished_at,
                            duration_ms,
                            encoded_metrics,
                            run_id,
                        ),
                    )
                else:
                    self._connection.execute(
                        """
                        UPDATE pipeline_runs
                        SET updated_at = ?, started_at = ?, finished_at = ?,
                            duration_ms = ?, metrics = ?
                        WHERE run_id = ?
                        """,
                        (
                            encoded_timestamp,
                            encoded_started_at,
                            encoded_finished_at,
                            duration_ms,
                            encoded_metrics,
                            run_id,
                        ),
                    )
            subscribers = tuple(self._subscribers.get(run_id, ()))

        event = PipelineRunEvent(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            timestamp=timestamp,
            parameters=dict(parameters),
        )
        self._publish_event(subscribers, event)

    def get_run(self, run_id: str) -> PipelineRun:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT run_id, pipeline, status, created_at, updated_at,
                       parameters, definition_snapshot, started_at, finished_at,
                       duration_ms, metrics
                FROM pipeline_runs
                WHERE run_id = ?
                """,
                (run_id,),
            )
            row = cursor.fetchone()
        if row is None:
            msg = f"run '{run_id}' could not be found"
            raise KeyError(msg)

        return PipelineRun(
            run_id=row["run_id"],
            pipeline=row["pipeline"],
            status=row["status"],
            created_at=self._decode_datetime(row["created_at"]),
            updated_at=self._decode_datetime(row["updated_at"]),
            parameters=self._decode_parameters(row["parameters"]),
            definition_snapshot=self._decode_definition_snapshot(
                row["definition_snapshot"]
            ),
            started_at=self._decode_optional_datetime(row["started_at"]),
            finished_at=self._decode_optional_datetime(row["finished_at"]),
            duration_ms=row["duration_ms"],
            metrics=self._normalise_metrics(self._decode_metrics(row["metrics"])),
        )

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[PipelineRun]:
        clauses: list[str] = []
        bindings: list[object] = []
        if pipeline is not None:
            clauses.append("pipeline = ?")
            bindings.append(pipeline)
        if status is not None:
            clauses.append("status = ?")
            bindings.append(status)
        if since is not None:
            clauses.append("created_at >= ?")
            bindings.append(self._encode_datetime(since))

        query = [
            (
                "SELECT run_id, pipeline, status, created_at, updated_at, "
                "parameters, definition_snapshot, started_at, finished_at, "
                "duration_ms, metrics"
            ),
            "FROM pipeline_runs",
        ]
        if clauses:
            query.append("WHERE " + " AND ".join(clauses))
        query.append("ORDER BY created_at DESC, run_id DESC")
        if limit is not None:
            query.append("LIMIT ?")

        statement = "\n".join(query)
        params: tuple[object, ...]
        if limit is not None:
            params = (*bindings, limit)
        else:
            params = tuple(bindings)

        with self._lock:
            cursor = self._connection.execute(statement, params)
            rows = cursor.fetchall()

        return [
            PipelineRun(
                run_id=row["run_id"],
                pipeline=row["pipeline"],
                status=row["status"],
                created_at=self._decode_datetime(row["created_at"]),
                updated_at=self._decode_datetime(row["updated_at"]),
                parameters=self._decode_parameters(row["parameters"]),
                definition_snapshot=self._decode_definition_snapshot(
                    row["definition_snapshot"]
                ),
                started_at=self._decode_optional_datetime(row["started_at"]),
                finished_at=self._decode_optional_datetime(row["finished_at"]),
                duration_ms=row["duration_ms"],
                metrics=self._normalise_metrics(self._decode_metrics(row["metrics"])),
            )
            for row in rows
        ]

    def iter_run_events(self, run_id: str) -> Iterator[PipelineRunEvent]:
        with self._lock:
            rows = self._load_run_event_rows_locked(run_id)

        for row in rows:
            yield self._row_to_run_event(row)

    def prune(
        self,
        *,
        max_age: timedelta | None = None,
        max_runs: int | None = None,
        now: datetime | None = None,
    ) -> PipelinePruneResult:
        if max_age is None and max_runs is None:
            with self._lock:
                remaining = self._count_runs_locked()
            return PipelinePruneResult(
                removed_runs=0,
                removed_events=0,
                remaining_runs=remaining,
                max_age=None,
                max_runs=None,
            )

        if max_age is not None and max_age.total_seconds() < 0:
            msg = "max_age must be non-negative"
            raise ValueError(msg)
        if max_runs is not None and max_runs < 0:
            msg = "max_runs must be non-negative"
            raise ValueError(msg)

        moment = now or datetime.now(timezone.utc)

        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT run_id, created_at
                FROM pipeline_runs
                ORDER BY created_at ASC, run_id ASC
                """
            )
            rows = cursor.fetchall()

            cutoff = moment - max_age if max_age is not None else None
            removal: list[str] = []

            for row in rows:
                if cutoff is None:
                    break
                created = self._decode_datetime(row["created_at"])
                if created < cutoff:
                    removal.append(row["run_id"])
                else:
                    break

            if max_runs is not None:
                retained = [
                    row["run_id"] for row in rows if row["run_id"] not in removal
                ]
                overflow = len(retained) - max_runs
                if overflow > 0:
                    removal.extend(retained[:overflow])

            if not removal:
                remaining = len(rows)
                return PipelinePruneResult(
                    removed_runs=0,
                    removed_events=0,
                    remaining_runs=remaining,
                    max_age=max_age,
                    max_runs=max_runs,
                )

            placeholders = ",".join("?" for _ in removal)
            parameters = tuple(removal)

            with self._connection:
                events_deleted = self._connection.execute(
                    f"DELETE FROM pipeline_run_events WHERE run_id IN ({placeholders})",
                    parameters,
                ).rowcount
                runs_deleted = self._connection.execute(
                    f"DELETE FROM pipeline_runs WHERE run_id IN ({placeholders})",
                    parameters,
                ).rowcount

            for run_id in removal:
                self._subscribers.pop(run_id, None)

            remaining = self._count_runs_locked()

        return PipelinePruneResult(
            removed_runs=int(runs_deleted or 0),
            removed_events=int(events_deleted or 0),
            remaining_runs=int(remaining),
            max_age=max_age,
            max_runs=max_runs,
        )

    def _count_runs_locked(self) -> int:
        cursor = self._connection.execute("SELECT COUNT(*) FROM pipeline_runs")
        row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def watch_run_events(self, run_id: str) -> AsyncIterator[PipelineRunEvent]:
        with self._lock:
            rows = self._load_run_event_rows_locked(run_id)

        events = [self._row_to_run_event(row) for row in rows]
        seen_count = len(events)

        subscriber: _RunEventSubscriber | None = None
        queue: asyncio.Queue[PipelineRunEvent] | None = None
        registered = False
        delivered_initial = False

        async def iterator() -> AsyncIterator[PipelineRunEvent]:
            nonlocal subscriber, queue, registered, delivered_initial, seen_count, events

            if not registered:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.get_event_loop_policy().new_event_loop()

                queue = asyncio.Queue()
                subscriber = _RunEventSubscriber(loop=loop, queue=queue)

                with self._lock:
                    rows_after_subscribe = self._load_run_event_rows_locked(run_id)
                    subscribers = self._subscribers.setdefault(run_id, [])
                    subscribers.append(subscriber)

                additional = [
                    self._row_to_run_event(row)
                    for row in rows_after_subscribe[seen_count:]
                ]
                if additional:
                    events.extend(additional)
                    seen_count = len(events)

                registered = True

            assert queue is not None
            assert subscriber is not None

            try:
                if not delivered_initial:
                    for event in events:
                        yield event
                    delivered_initial = True

                while True:
                    yield await queue.get()
            finally:
                with self._lock:
                    targets = self._subscribers.get(run_id)
                    if targets is not None and subscriber in targets:
                        targets.remove(subscriber)
                        if not targets:
                            self._subscribers.pop(run_id, None)

        return iterator()

    def _publish_event(
        self,
        subscribers: tuple[_RunEventSubscriber, ...],
        event: PipelineRunEvent,
    ) -> None:
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(subscriber.queue.put_nowait, event)

    def _load_run_event_rows_locked(self, run_id: str) -> list[sqlite3.Row]:
        cursor = self._connection.execute(
            """
            SELECT run_id, pipeline, status, timestamp, parameters
            FROM pipeline_run_events
            WHERE run_id = ?
            ORDER BY id ASC
            """,
            (run_id,),
        )
        rows = cursor.fetchall()
        if rows:
            return rows
        cursor = self._connection.execute(
            "SELECT 1 FROM pipeline_runs WHERE run_id = ?",
            (run_id,),
        )
        if cursor.fetchone() is None:
            msg = f"run '{run_id}' could not be found"
            raise KeyError(msg)
        return rows

    def _row_to_run_event(self, row: sqlite3.Row) -> PipelineRunEvent:
        return PipelineRunEvent(
            run_id=row["run_id"],
            pipeline=row["pipeline"],
            status=row["status"],
            timestamp=self._decode_datetime(row["timestamp"]),
            parameters=self._decode_parameters(row["parameters"]),
        )

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> PipelineRunStore:
        database = config.get("database") or config.get("path")
        if database is None:
            msg = "storage configuration requires a 'database' or 'path' value"
            raise ValueError(msg)
        busy_timeout = config.get("busy_timeout")
        busy_timeout_ms = config.get("busy_timeout_ms")
        if busy_timeout is not None and busy_timeout_ms is not None:
            msg = "provide only one of 'busy_timeout' or 'busy_timeout_ms'"
            raise ValueError(msg)
        if busy_timeout_ms is not None:
            try:
                busy_timeout = float(busy_timeout_ms) / 1000
            except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                raise ValueError("busy_timeout_ms must be numeric") from exc
        return cls(database=database, busy_timeout=busy_timeout)


class PipelineOrchestrator:
    """Pipeline orchestrator used by the Trafalgar tooling layer.

    Runs and events are persisted through a configurable :class:`PipelineRunStore`.
    """

    def __init__(
        self,
        definitions: Iterable[PipelineDefinition] | None = None,
        *,
        store: PipelineRunStore | None = None,
        executor: pipeline_executor.PipelineExecutor | None = None,
        worker_pool: ThreadPoolExecutor | None = None,
        retention: PipelineRetentionPolicy | None = None,
    ) -> None:
        self._definitions: dict[str, PipelineDefinition] = {}
        self._lock = Lock()
        self._store = store or PipelineRunStore()
        self._executor = executor or pipeline_executor.PipelineExecutor()
        self._worker_pool = worker_pool or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="pipeline-runs"
        )
        self._shutdown = False
        self._pending: set[Future[None]] = set()
        self._retention = retention
        if definitions:
            for definition in definitions:
                self.register(definition)

    def register(self, definition: PipelineDefinition) -> None:
        stored = self._prepare_definition(definition)
        with self._lock:
            if definition.name in self._definitions:
                msg = f"pipeline '{definition.name}' is already registered"
                raise ValueError(msg)
            self._definitions[definition.name] = stored

    def upsert(self, definition: PipelineDefinition) -> bool:
        stored = self._prepare_definition(definition)
        with self._lock:
            created = definition.name not in self._definitions
            self._definitions[definition.name] = stored
        return created

    def deregister(self, name: str) -> None:
        with self._lock:
            try:
                del self._definitions[name]
            except KeyError as exc:
                msg = f"pipeline '{name}' is not registered"
                raise KeyError(msg) from exc

    def list_pipelines(self) -> list[PipelineDefinition]:
        with self._lock:
            definitions = list(self._definitions.values())
        return sorted(definitions, key=lambda item: item.name)

    def get_pipeline(self, name: str) -> PipelineDefinition:
        with self._lock:
            try:
                return self._definitions[name]
            except KeyError as exc:  # pragma: no cover - defensive guard
                msg = f"pipeline '{name}' is not registered"
                raise KeyError(msg) from exc

    def _prepare_definition(self, definition: PipelineDefinition) -> PipelineDefinition:
        resolved = self._executor.resolve_pipeline(definition.pipeline)
        return replace(definition, pipeline=resolved)

    def trigger_run(
        self, pipeline_name: str, *, parameters: Mapping[str, Any] | None = None
    ) -> PipelineRun:
        parameters = dict(parameters or {})
        definition = self.get_pipeline(pipeline_name)
        definition_snapshot = definition.serialise()
        run_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id=run_id,
            pipeline=definition.name,
            status="queued",
            created_at=now,
            updated_at=now,
            parameters=parameters,
            definition_snapshot=definition_snapshot,
        )
        initial_event = PipelineRunEvent(
            run_id=run_id,
            pipeline=definition.name,
            status="queued",
            timestamp=run.created_at,
            parameters=parameters,
        )
        self._store.create_run(run, initial_event)
        future = self._submit_run(
            definition=definition, run_id=run_id, parameters=parameters
        )
        self._register_future(future)

        return self._store.get_run(run_id)

    def _submit_run(
        self,
        *,
        definition: PipelineDefinition,
        run_id: str,
        parameters: Mapping[str, Any],
    ) -> Future[None]:
        if self._shutdown:
            msg = "pipeline orchestrator has been shut down"
            raise RuntimeError(msg)

        def _runner() -> None:
            self._append_event(run_id, "running")
            try:
                self._executor.execute(
                    definition.pipeline,
                    parameters=parameters,
                    emit=self._build_step_emitter(run_id),
                )
            except Exception as exc:
                self._append_event(
                    run_id,
                    "failed",
                    parameters={"error": str(exc)},
                )
            else:
                self._append_event(run_id, "succeeded")

        return self._worker_pool.submit(_runner)

    def _register_future(self, future: Future[None]) -> None:
        def _cleanup(completed: Future[None]) -> None:
            with self._lock:
                self._pending.discard(completed)

        with self._lock:
            self._pending.add(future)
        future.add_done_callback(_cleanup)

    def shutdown(self, *, wait: bool = True) -> None:
        if not self._shutdown:
            self._shutdown = True
            self._worker_pool.shutdown(wait=wait)
            with self._lock:
                self._pending.clear()
        self._store.close()

    def _build_step_emitter(self, run_id: str) -> pipeline_executor.StepEventEmitter:
        starts: dict[str, list[datetime]] = {}
        lock = Lock()

        def emit(
            status: str,
            *,
            step: pipeline_executor.ExecutedStep,
            event: pipeline_executor.StepTriggerEvent | None = None,
            error: Exception | None = None,
        ) -> None:
            payload: dict[str, Any] = {"step": step.name}
            now = datetime.now(timezone.utc)

            if status == "step_started":
                started_at = now
                payload["started_at"] = started_at.isoformat()
                with lock:
                    starts.setdefault(step.name, []).append(started_at)
            elif status in {"step_succeeded", "step_failed"}:
                with lock:
                    stack = starts.get(step.name)
                    started_at = stack.pop() if stack else None  # type: ignore[assignment]
                    if stack is not None and not stack:
                        starts.pop(step.name, None)
                if started_at is None:
                    started_at = now
                finished_at = now
                duration_ms = max(
                    int((finished_at - started_at).total_seconds() * 1000), 0
                )
                payload.update(
                    {
                        "started_at": started_at.isoformat(),
                        "finished_at": finished_at.isoformat(),
                        "duration_ms": duration_ms,
                    }
                )

            if event is not None:
                payload["event"] = {
                    "name": event.name,
                    "payload": dict(event.payload),
                }
            if error is not None:
                payload["error"] = str(error)
            self._append_event(run_id, status, parameters=payload)

        return emit

    def _append_event(
        self,
        run_id: str,
        status: str,
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc)
        parameters = dict(parameters or {})
        run_status: str | None
        if status in {"queued", "running", "succeeded", "failed"}:
            run_status = status
        elif status == "step_failed":
            run_status = "failed"
        else:
            run_status = None
        self._store.append_event(
            run_id,
            status=status,
            timestamp=timestamp,
            parameters=parameters,
            run_status=run_status,
        )

    def get_run(self, run_id: str) -> PipelineRun:
        try:
            return self._store.get_run(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: datetime | None = None,
    ) -> list[PipelineRun]:
        return self._store.list_runs(
            pipeline=pipeline, status=status, limit=limit, since=since
        )

    def iter_run_events(self, run_id: str) -> Iterator[PipelineRunEvent]:
        try:
            return self._store.iter_run_events(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def watch_run_events(self, run_id: str) -> AsyncIterator[PipelineRunEvent]:
        try:
            return self._store.watch_run_events(run_id)
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(str(exc)) from exc

    def serialise_run(self, run_id: str) -> Mapping[str, Any]:
        run = self.get_run(run_id)
        return run.serialise()

    def serialise_run_events(self, run_id: str) -> list[Mapping[str, Any]]:
        return [event.serialise() for event in self.iter_run_events(run_id)]

    @property
    def retention_policy(self) -> PipelineRetentionPolicy | None:
        return self._retention

    def prune_history(
        self,
        *,
        max_age: timedelta | None = None,
        max_runs: int | None = None,
        now: datetime | None = None,
    ) -> PipelinePruneResult:
        if max_age is None and max_runs is None and self._retention is not None:
            max_age = self._retention.max_age
            max_runs = self._retention.max_runs
        return self._store.prune(max_age=max_age, max_runs=max_runs, now=now)


_default_orchestrator: PipelineOrchestrator | None = None


def get_pipeline_orchestrator(
    *,
    storage: PipelineRunStore | None = None,
    storage_config: Mapping[str, Any] | None = None,
) -> PipelineOrchestrator:
    global _default_orchestrator
    if _default_orchestrator is None:
        if storage is not None and storage_config is not None:
            msg = "provide either a storage instance or configuration, not both"
            raise ValueError(msg)
        retention: PipelineRetentionPolicy | None = None
        if storage is None and storage_config is not None:
            storage = PipelineRunStore.from_config(storage_config)
            retention = _retention_policy_from_storage(storage_config)
        _default_orchestrator = PipelineOrchestrator(store=storage, retention=retention)
    elif storage is not None or storage_config is not None:
        msg = (
            "pipeline orchestrator is already configured; "
            "reset it with set_pipeline_orchestrator(None) before supplying storage"
        )
        raise RuntimeError(msg)
    return _default_orchestrator


def set_pipeline_orchestrator(orchestrator: PipelineOrchestrator | None) -> None:
    global _default_orchestrator
    if _default_orchestrator is not None and _default_orchestrator is not orchestrator:
        previous = _default_orchestrator
        previous.shutdown()
        previous._store.close()
    _default_orchestrator = orchestrator


def pipeline_definition_from_profile_entry(
    name: str, config: Mapping[str, Any]
) -> PipelineDefinition:
    """Return a pipeline definition derived from profile configuration."""

    pipeline_config = dict(config)
    pipeline_config.setdefault("name", name)
    pipeline = pipeline_from_config(pipeline_config)

    metadata = pipeline.metadata or {}

    def _coerce_optional_str(value: Any) -> str | None:
        if value is None:
            return None
        return str(value)

    display_name = _coerce_optional_str(
        config.get("display_name", metadata.get("display_name"))
    )
    description = _coerce_optional_str(
        config.get("description", metadata.get("description"))
    )

    parameters_raw = config.get("parameters")
    if parameters_raw is None:
        parameters: Mapping[str, Any] = {}
    elif isinstance(parameters_raw, Mapping):
        parameters = dict(parameters_raw)
    else:
        msg = f"pipeline '{name}' parameters must be a mapping"
        raise TypeError(msg)

    return PipelineDefinition(
        name=pipeline.name,
        pipeline=pipeline,
        display_name=display_name,
        description=description,
        parameters=parameters,
    )


def _retention_policy_from_storage(
    storage_config: Mapping[str, Any]
) -> PipelineRetentionPolicy | None:
    retention_config = storage_config.get("retention")
    if retention_config is None:
        return None
    if not isinstance(retention_config, Mapping):
        msg = "pipeline.storage.retention must be a mapping"
        raise ValueError(msg)
    retention_mapping = cast(Mapping[str, Any], retention_config)
    return PipelineRetentionPolicy.from_mapping(retention_mapping)


def pipeline_definitions_from_profile(
    profile: ProfileContext,
) -> tuple[PipelineDefinition, ...]:
    """Build pipeline definitions from a loaded profile context."""

    return tuple(
        pipeline_definition_from_profile_entry(name, config)
        for name, config in sorted(profile.pipelines.items())
    )


def configure_orchestrator_from_profile(
    profile: ProfileContext,
    *,
    storage_config: Mapping[str, Any] | None = None,
) -> PipelineOrchestrator:
    """Initialise the shared orchestrator with definitions from *profile*.

    When a storage configuration mapping is supplied the orchestrator persists
    pipeline run history using :class:`PipelineRunStore`.
    """

    definitions = pipeline_definitions_from_profile(profile)
    effective_storage = storage_config or profile.pipeline_storage
    retention = None
    store = None
    if effective_storage:
        retention = _retention_policy_from_storage(effective_storage)
        store = PipelineRunStore.from_config(effective_storage)
    orchestrator = PipelineOrchestrator(definitions, store=store, retention=retention)
    set_pipeline_orchestrator(orchestrator)
    return orchestrator


__all__ = [
    "PipelineDefinition",
    "PipelineOrchestrator",
    "PipelineRun",
    "PipelineRunEvent",
    "PipelineRunStore",
    "PipelineRetentionPolicy",
    "PipelinePruneResult",
    "get_pipeline_orchestrator",
    "set_pipeline_orchestrator",
    "pipeline_definition_from_profile_entry",
    "pipeline_definitions_from_profile",
    "configure_orchestrator_from_profile",
]
