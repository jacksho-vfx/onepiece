"""Pipeline run storage implementation for Trafalgar orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from types import TracebackType
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, AsyncIterator, Iterable, Iterator, Mapping

from .models import (
    PipelinePruneResult,
    PipelineRun,
    PipelineRunCursor,
    PipelineRunEvent,
    PipelineRunPage,
    _RunEventSubscriber,
)

__all__ = [
    "PipelineRunStore",
]


logger = logging.getLogger(__name__)


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
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
        self._busy_timeout_ms = busy_timeout_ms
        self._initialise_schema()
        self._subscribers: dict[str, list[_RunEventSubscriber]] = {}
        self._closed = False

    def __enter__(self) -> PipelineRunStore:
        """Enter the context manager and return the store instance."""

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Close the store when exiting a context block."""

        self.close()

    def close(self) -> None:
        """Release any database resources held by the store."""

        with self._lock:
            if self._closed:
                return
            self._closed = True
            active_subscribers = tuple(
                subscriber
                for subscribers in self._subscribers.values()
                for subscriber in subscribers
            )
            self._subscribers = {}
            connection = self._connection

        try:
            connection.close()
        finally:
            if active_subscribers:
                self._notify_subscribers(active_subscribers, None)

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
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to decode pipeline parameters payload; using defaults",
                exc_info=True,
            )
            return {}
        if isinstance(data, dict):
            return data
        logger.warning("Pipeline parameters payload was not a mapping; using defaults")
        return {}

    @staticmethod
    def _encode_definition_snapshot(snapshot: Mapping[str, Any]) -> str:
        return json.dumps(dict(snapshot))

    @staticmethod
    def _decode_definition_snapshot(payload: str | None) -> dict[str, Any]:
        if not payload:
            return {}
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to decode definition snapshot payload; using defaults",
                exc_info=True,
            )
            return {}
        if isinstance(data, dict):
            return data
        logger.warning("Definition snapshot payload was not a mapping; using defaults")
        return {}

    @staticmethod
    def _encode_roles(roles: Iterable[str]) -> str:
        return json.dumps(list(roles))

    @staticmethod
    def _decode_roles(payload: str | None) -> tuple[str, ...]:
        if not payload:
            return ()
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError:
            return ()
        if not isinstance(decoded, list):
            return ()
        seen: set[str] = set()
        ordered: list[str] = []
        for role in decoded:
            text = str(role).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ordered.append(text)
        return tuple(sorted(ordered))

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
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to decode metrics payload; using defaults", exc_info=True
            )
            return {}
        if isinstance(data, dict):
            return data
        logger.warning("Metrics payload was not a mapping; using defaults")
        return {}

    @staticmethod
    def _initial_metrics() -> dict[str, Any]:
        return {
            "steps": {},
            "totals": {
                "step_duration_ms": 0,
                "queue_wait": {},
            },
        }

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
        queue_source = totals.get("queue_wait", {})
        if isinstance(queue_source, dict):
            totals["queue_wait"] = dict(queue_source)
        else:
            totals["queue_wait"] = {}
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
        queue_totals = totals.setdefault("queue_wait", {})
        if not isinstance(queue_totals, dict):
            queue_totals = {}
            totals["queue_wait"] = queue_totals

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

        def _to_int(value: Any) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        if run_status == "queued":
            queue_totals["last_queued_at"] = timestamp.isoformat()

        if run_status == "running":
            anchor_text = queue_totals.pop("last_queued_at", None)
            anchor = None
            if isinstance(anchor_text, str):
                try:
                    parsed = datetime.fromisoformat(anchor_text)
                except ValueError:
                    parsed = None
                if parsed is not None:
                    if parsed.tzinfo is None:
                        anchor = parsed.replace(tzinfo=timezone.utc)
                    else:
                        anchor = parsed.astimezone(timezone.utc)
            if anchor is None:
                anchor = created_at
            if anchor is not None:
                wait_delta = timestamp - anchor
                wait_ms = int(max(wait_delta.total_seconds() * 1000, 0))
                existing_total = _to_int(queue_totals.get("total_ms")) or 0
                queue_totals["total_ms"] = existing_total + wait_ms
                existing_count = _to_int(queue_totals.get("count")) or 0
                queue_totals["count"] = existing_count + 1
                queue_totals["last_wait_ms"] = wait_ms

                previous_min = _to_int(queue_totals.get("min_ms"))
                if previous_min is None or wait_ms < previous_min:
                    queue_totals["min_ms"] = wait_ms
                else:
                    queue_totals["min_ms"] = previous_min

                previous_max = _to_int(queue_totals.get("max_ms"))
                if previous_max is None or wait_ms > previous_max:
                    queue_totals["max_ms"] = wait_ms
                else:
                    queue_totals["max_ms"] = previous_max

            if current_started is None:
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
                    metrics TEXT NOT NULL DEFAULT '{}',
                    submitted_by TEXT,
                    submitted_roles TEXT
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
        if "submitted_by" not in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN submitted_by TEXT"
                )
        if "submitted_roles" not in columns:
            with self._connection:
                self._connection.execute(
                    "ALTER TABLE pipeline_runs ADD COLUMN submitted_roles TEXT"
                )

    def create_run(self, run: PipelineRun, initial_event: PipelineRunEvent) -> None:
        payload = self._encode_parameters(run.parameters)
        definition_payload = self._encode_definition_snapshot(run.definition_snapshot)
        event_payload = self._encode_parameters(initial_event.parameters)
        metrics = self._normalise_metrics(run.metrics)
        totals = metrics.setdefault("totals", {})
        queue_totals = totals.setdefault("queue_wait", {})
        if not isinstance(queue_totals, dict):
            queue_totals = {}
            totals["queue_wait"] = queue_totals
        queue_totals.setdefault("total_ms", 0)
        queue_totals.setdefault("count", 0)
        queue_totals.setdefault("min_ms", None)
        queue_totals.setdefault("max_ms", None)
        queue_totals["last_queued_at"] = run.created_at.isoformat()
        metrics_payload = self._encode_metrics(metrics)
        encoded_started_at = self._encode_optional_datetime(run.started_at)
        encoded_finished_at = self._encode_optional_datetime(run.finished_at)
        encoded_roles = self._encode_roles(run.roles)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO pipeline_runs (
                    run_id, pipeline, status, created_at, updated_at, parameters,
                    definition_snapshot, started_at, finished_at, duration_ms, metrics,
                    submitted_by, submitted_roles
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    run.submitted_by,
                    encoded_roles,
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
        stored_parameters = dict(parameters)
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
            encoded_parameters = self._encode_parameters(stored_parameters)
            encoded_timestamp = self._encode_datetime(timestamp)

            metrics, started_at, finished_at, duration_ms = self._apply_event_metrics(
                metrics=metrics,
                status=status,
                timestamp=timestamp,
                parameters=stored_parameters,
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
                cursor = self._connection.execute(
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

        inserted_event_id = int(cursor.lastrowid or 0)
        event = PipelineRunEvent(
            event_id=inserted_event_id if inserted_event_id > 0 else None,
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            timestamp=timestamp,
            parameters=stored_parameters,
        )
        self._publish_event(subscribers, event)

    def get_run(self, run_id: str) -> PipelineRun:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT run_id, pipeline, status, created_at, updated_at,
                       parameters, definition_snapshot, started_at, finished_at,
                       duration_ms, metrics, submitted_by, submitted_roles
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
            submitted_by=row["submitted_by"],
            roles=self._decode_roles(row["submitted_roles"]),
        )

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: datetime | None = None,
        before_id: str | None = None,
        before_created_at: datetime | None = None,
        submitted_by: str | None = None,
        role: str | None = None,
    ) -> PipelineRunPage:
        if (before_id is None) ^ (before_created_at is None):
            msg = "'before_id' and 'before_created_at' must be supplied together"
            raise ValueError(msg)

        clauses: list[str] = []
        bindings: list[object] = []
        if pipeline is not None:
            clauses.append("pipeline = ?")
            bindings.append(pipeline)
        if status is not None:
            clauses.append("status = ?")
            bindings.append(status)
        if submitted_by is not None:
            clauses.append("submitted_by = ?")
            bindings.append(submitted_by)
        if role is not None:
            clauses.append(
                "EXISTS ("
                "SELECT 1 FROM json_each(COALESCE(submitted_roles, '[]')) "
                "WHERE value = ?"
                ")"
            )
            bindings.append(role)
        if since is not None:
            clauses.append("created_at >= ?")
            bindings.append(self._encode_datetime(since))
        if before_id is not None and before_created_at is not None:
            encoded = self._encode_datetime(before_created_at)
            clauses.append("(created_at < ? OR (created_at = ? AND run_id < ?))")
            bindings.extend([encoded, encoded, before_id])

        query = [
            (
                "SELECT run_id, pipeline, status, created_at, updated_at, "
                "parameters, definition_snapshot, started_at, finished_at, "
                "duration_ms, metrics, submitted_by, submitted_roles"
            ),
            "FROM pipeline_runs",
        ]
        if clauses:
            query.append("WHERE " + " AND ".join(clauses))
        query.append("ORDER BY created_at DESC, run_id DESC")
        effective_limit = None
        if limit is not None:
            effective_limit = limit + 1
            query.append("LIMIT ?")

        statement = "\n".join(query)
        params: tuple[object, ...]
        if effective_limit is not None:
            params = (*bindings, effective_limit)
        else:
            params = tuple(bindings)

        with self._lock:
            cursor = self._connection.execute(statement, params)
            rows = cursor.fetchall()

        has_more = False
        if limit is not None and len(rows) > limit:
            has_more = True
            rows = rows[:limit]

        runs = [
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
                submitted_by=row["submitted_by"],
                roles=self._decode_roles(row["submitted_roles"]),
            )
            for row in rows
        ]

        next_cursor: PipelineRunCursor | None = None
        if has_more and runs:
            last = runs[-1]
            next_cursor = PipelineRunCursor(
                before_id=last.run_id,
                before_created_at=last.created_at,
            )

        return PipelineRunPage(runs=runs, next_cursor=next_cursor)

    def aggregate_runs(
        self,
        *,
        since: datetime | None = None,
        include_durations: bool = False,
        pipeline: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Return aggregated run statistics grouped by pipeline and status."""

        class _QueueMetrics:
            __slots__ = ("total_seconds", "count", "min_seconds", "max_seconds")

            def __init__(
                self,
                *,
                total_seconds: float,
                count: int,
                min_seconds: float,
                max_seconds: float,
            ) -> None:
                self.total_seconds = total_seconds
                self.count = count
                self.min_seconds = min_seconds
                self.max_seconds = max_seconds

        class _Accumulator:
            __slots__ = (
                "count",
                "duration_sum",
                "duration_count",
                "duration_min",
                "duration_max",
                "queue_wait_sum",
                "queue_wait_count",
                "queue_wait_min",
                "queue_wait_max",
            )

            def __init__(self) -> None:
                self.count = 0
                self.duration_sum = 0.0
                self.duration_count = 0
                self.duration_min: float | None = None
                self.duration_max: float | None = None
                self.queue_wait_sum = 0.0
                self.queue_wait_count = 0
                self.queue_wait_min: float | None = None
                self.queue_wait_max: float | None = None

            def record(
                self,
                *,
                duration: float | None,
                queue: _QueueMetrics | None,
            ) -> None:
                self.count += 1
                if duration is not None:
                    self.duration_sum += duration
                    self.duration_count += 1
                    if self.duration_min is None or duration < self.duration_min:
                        self.duration_min = duration
                    if self.duration_max is None or duration > self.duration_max:
                        self.duration_max = duration
                if queue is None or queue.count <= 0:
                    return
                self.queue_wait_sum += queue.total_seconds
                self.queue_wait_count += queue.count
                if (
                    self.queue_wait_min is None
                    or queue.min_seconds < self.queue_wait_min
                ):
                    self.queue_wait_min = queue.min_seconds
                if (
                    self.queue_wait_max is None
                    or queue.max_seconds > self.queue_wait_max
                ):
                    self.queue_wait_max = queue.max_seconds

            def serialise(
                self,
                *,
                include_durations: bool,
                status: str,
            ) -> dict[str, Any]:
                payload: dict[str, Any] = {"count": self.count}
                if include_durations and self.duration_count:
                    average = self.duration_sum / self.duration_count
                    payload["durations"] = {
                        "average_seconds": average,
                        "min_seconds": self.duration_min,
                        "max_seconds": self.duration_max,
                    }
                if include_durations and self.queue_wait_count:
                    queue_average = self.queue_wait_sum / self.queue_wait_count
                    payload["queue_waits"] = {
                        "average_seconds": queue_average,
                        "min_seconds": self.queue_wait_min,
                        "max_seconds": self.queue_wait_max,
                    }
                if status == "queued":
                    payload["backlog_count"] = self.count
                return payload

        def _to_int(value: Any) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        def _extract_queue_metrics(payload: Mapping[str, Any]) -> _QueueMetrics | None:
            totals = payload.get("totals")
            if not isinstance(totals, Mapping):
                return None
            queue = totals.get("queue_wait")
            if not isinstance(queue, Mapping):
                return None
            count = _to_int(queue.get("count"))
            total_ms = _to_int(queue.get("total_ms"))
            if count is None or count <= 0 or total_ms is None:
                return None
            min_ms = _to_int(queue.get("min_ms"))
            max_ms = _to_int(queue.get("max_ms"))
            total_seconds = total_ms / 1000.0
            average_seconds = total_seconds / count if count else 0.0
            min_seconds = min_ms / 1000.0 if min_ms is not None else average_seconds
            max_seconds = max_ms / 1000.0 if max_ms is not None else average_seconds
            return _QueueMetrics(
                total_seconds=total_seconds,
                count=count,
                min_seconds=min_seconds,
                max_seconds=max_seconds,
            )

        clauses: list[str] = []
        bindings: list[object] = []
        if since is not None:
            clauses.append("created_at >= ?")
            bindings.append(self._encode_datetime(since))
        if pipeline is not None:
            clauses.append("pipeline = ?")
            bindings.append(str(pipeline))

        select_fields = ["pipeline", "status", "created_at", "updated_at"]
        if include_durations:
            select_fields.append("metrics")
        query = [
            "SELECT " + ", ".join(select_fields),
            "FROM pipeline_runs",
        ]
        if clauses:
            query.append("WHERE " + " AND ".join(clauses))

        statement = "\n".join(query)
        params = tuple(bindings)

        with self._lock:
            cursor = self._connection.execute(statement, params)
            rows = cursor.fetchall()

        grouped: dict[str, dict[str, _Accumulator]] = {}
        for row in rows:
            pipeline = str(row["pipeline"])
            status = str(row["status"])
            created = self._decode_datetime(row["created_at"])
            updated = self._decode_datetime(row["updated_at"])
            duration = (updated - created).total_seconds()
            queue_metrics: _QueueMetrics | None = None
            if include_durations:
                metrics_payload = row["metrics"]
                if metrics_payload is not None:
                    decoded = self._normalise_metrics(
                        self._decode_metrics(metrics_payload)
                    )
                    queue_metrics = _extract_queue_metrics(decoded)
            bucket = grouped.setdefault(pipeline, {})
            accumulator = bucket.setdefault(status, _Accumulator())
            accumulator.record(
                duration=duration if include_durations else None,
                queue=queue_metrics if include_durations else None,
            )

        result: dict[str, dict[str, dict[str, Any]]] = {}
        for pipeline in sorted(grouped):
            status_payload: dict[str, dict[str, Any]] = {}
            for status in sorted(grouped[pipeline]):
                accumulator = grouped[pipeline][status]
                status_payload[status] = accumulator.serialise(
                    include_durations=include_durations,
                    status=status,
                )
            result[pipeline] = status_payload
        return result

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
        max_runs_per_pipeline: Mapping[str, int] | None = None,
    ) -> PipelinePruneResult:
        per_pipeline_limits: dict[str, int] = {}
        if max_runs_per_pipeline:
            for name, raw_value in max_runs_per_pipeline.items():
                limit = int(raw_value)
                if limit < 0:
                    msg = "max_runs per pipeline must be non-negative"
                    raise ValueError(msg)
                per_pipeline_limits[str(name)] = limit

        if max_age is None and max_runs is None and not per_pipeline_limits:
            with self._lock:
                remaining = self._count_runs_locked()
            return PipelinePruneResult(
                removed_runs=0,
                removed_events=0,
                remaining_runs=remaining,
                max_age=None,
                max_runs=None,
                removed_runs_by_pipeline={},
            )

        if max_age is not None and max_age.total_seconds() < 0:
            msg = "max_age must be non-negative"
            raise ValueError(msg)
        if max_runs is not None and max_runs < 0:
            msg = "max_runs must be non-negative"
            raise ValueError(msg)

        moment = now or datetime.now(timezone.utc)

        removed_subscribers: list[_RunEventSubscriber] = []

        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT run_id, pipeline, created_at
                FROM pipeline_runs
                ORDER BY created_at ASC, run_id ASC
                """
            )
            rows = cursor.fetchall()

            cutoff = moment - max_age if max_age is not None else None
            removal_set: set[str] = set()
            removal_order: list[str] = []
            removed_by_pipeline: dict[str, int] = {}
            rows_by_pipeline: dict[str, list[sqlite3.Row]] = {}

            def _mark_for_removal(run_id: str, pipeline: str) -> None:
                if run_id in removal_set:
                    return
                removal_set.add(run_id)
                removal_order.append(run_id)
                removed_by_pipeline[pipeline] = removed_by_pipeline.get(pipeline, 0) + 1

            for row in rows:
                pipeline = str(row["pipeline"])
                rows_by_pipeline.setdefault(pipeline, []).append(row)

                if cutoff is None:
                    continue

                created = self._decode_datetime(row["created_at"])
                if created < cutoff:
                    _mark_for_removal(str(row["run_id"]), pipeline)

            for pipeline, pipeline_rows in rows_by_pipeline.items():
                if pipeline in per_pipeline_limits:
                    limit_value: int | None = per_pipeline_limits[pipeline]
                else:
                    limit_value = max_runs
                if limit_value is None:
                    continue
                retained_rows = [
                    row
                    for row in pipeline_rows
                    if str(row["run_id"]) not in removal_set
                ]
                overflow = len(retained_rows) - limit_value
                if overflow <= 0:
                    continue
                for row in retained_rows[:overflow]:
                    _mark_for_removal(str(row["run_id"]), pipeline)

            if not removal_order:
                remaining = len(rows)
                return PipelinePruneResult(
                    removed_runs=0,
                    removed_events=0,
                    remaining_runs=remaining,
                    max_age=max_age,
                    max_runs=max_runs,
                    removed_runs_by_pipeline={},
                )

            placeholders = ",".join("?" for _ in removal_order)
            parameters = tuple(removal_order)

            with self._connection:
                events_deleted = self._connection.execute(
                    f"DELETE FROM pipeline_run_events WHERE run_id IN ({placeholders})",
                    parameters,
                ).rowcount
                runs_deleted = self._connection.execute(
                    f"DELETE FROM pipeline_runs WHERE run_id IN ({placeholders})",
                    parameters,
                ).rowcount

            for run_id in removal_order:
                subscribers = self._subscribers.pop(run_id, None)
                if subscribers:
                    removed_subscribers.extend(subscribers)

            remaining = self._count_runs_locked()

        if removed_subscribers:
            self._notify_subscribers(removed_subscribers, None)

        return PipelinePruneResult(
            removed_runs=int(runs_deleted or 0),
            removed_events=int(events_deleted or 0),
            remaining_runs=int(remaining),
            max_age=max_age,
            max_runs=max_runs,
            removed_runs_by_pipeline=removed_by_pipeline,
        )

    def _count_runs_locked(self) -> int:
        cursor = self._connection.execute("SELECT COUNT(*) FROM pipeline_runs")
        row = cursor.fetchone()
        return int(row[0]) if row is not None else 0

    def watch_run_events(
        self,
        run_id: str,
        *,
        after_event_id: int | None = None,
        since_timestamp: datetime | None = None,
    ) -> AsyncIterator[PipelineRunEvent]:
        if since_timestamp is not None:
            if since_timestamp.tzinfo is None:
                since_timestamp = since_timestamp.replace(tzinfo=timezone.utc)
            else:
                since_timestamp = since_timestamp.astimezone(timezone.utc)

        last_event_id = after_event_id
        pending_since = since_timestamp if last_event_id is None else None

        with self._lock:
            rows = self._load_run_event_rows_locked(
                run_id,
                after_event_id=last_event_id,
                since_timestamp=pending_since,
            )

        events = [self._row_to_run_event(row) for row in rows]
        if events:
            last_event_id = events[-1].event_id
            pending_since = None

        subscriber: _RunEventSubscriber | None = None
        queue: asyncio.Queue[PipelineRunEvent | None] | None = None
        registered = False
        delivered_initial = False

        async def iterator() -> AsyncIterator[PipelineRunEvent]:
            nonlocal subscriber, queue, registered, delivered_initial, events
            nonlocal last_event_id, pending_since

            if not registered:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.get_event_loop_policy().new_event_loop()

                queue = asyncio.Queue()
                subscriber = _RunEventSubscriber(loop=loop, queue=queue)

                with self._lock:
                    rows_after_subscribe = self._load_run_event_rows_locked(
                        run_id,
                        after_event_id=last_event_id,
                        since_timestamp=pending_since,
                    )
                    subscribers = self._subscribers.setdefault(run_id, [])
                    subscribers.append(subscriber)

                additional = [
                    self._row_to_run_event(row) for row in rows_after_subscribe
                ]
                if additional:
                    events.extend(additional)
                    last_event_id = additional[-1].event_id
                    pending_since = None

                registered = True

            assert queue is not None
            assert subscriber is not None

            try:
                if not delivered_initial:
                    for event in events:
                        last_event_id = event.event_id
                        pending_since = None
                        yield event
                    delivered_initial = True

                while True:
                    item = await queue.get()
                    if item is None:
                        break
                    if item.event_id is not None:
                        if last_event_id is not None and item.event_id <= last_event_id:
                            continue
                        last_event_id = item.event_id
                        pending_since = None
                    yield item
            finally:
                with self._lock:
                    targets = self._subscribers.get(run_id)
                    if targets is not None and subscriber in targets:
                        targets.remove(subscriber)
                        if not targets:
                            self._subscribers.pop(run_id, None)

        return iterator()

    def _notify_subscribers(
        self,
        subscribers: Iterable[_RunEventSubscriber],
        payload: PipelineRunEvent | None,
    ) -> None:
        for subscriber in subscribers:
            try:
                subscriber.loop.call_soon_threadsafe(
                    subscriber.queue.put_nowait, payload
                )
            except RuntimeError:
                continue

    def _publish_event(
        self,
        subscribers: tuple[_RunEventSubscriber, ...],
        event: PipelineRunEvent,
    ) -> None:
        self._notify_subscribers(subscribers, event)

    def _load_run_event_rows_locked(
        self,
        run_id: str,
        *,
        after_event_id: int | None = None,
        since_timestamp: datetime | None = None,
    ) -> list[sqlite3.Row]:
        clauses = ["run_id = ?"]
        bindings: list[object] = [run_id]
        if after_event_id is not None:
            clauses.append("id > ?")
            bindings.append(int(after_event_id))
        if since_timestamp is not None:
            clauses.append("timestamp > ?")
            bindings.append(self._encode_datetime(since_timestamp))

        where_clause = " AND ".join(clauses)
        cursor = self._connection.execute(
            f"""
            SELECT id, run_id, pipeline, status, timestamp, parameters
            FROM pipeline_run_events
            WHERE {where_clause}
            ORDER BY id ASC
            """,
            tuple(bindings),
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
            event_id=int(row["id"]),
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
