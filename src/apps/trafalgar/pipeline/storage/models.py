"""Data models used by Trafalgar pipeline storage."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

__all__ = [
    "PipelineRunCursor",
    "PipelineRunPage",
    "PipelineRun",
    "PipelineRunEvent",
    "_RunEventSubscriber",
    "PipelineRetentionPolicy",
    "PipelinePruneResult",
]


@dataclass(frozen=True, slots=True)
class PipelineRunCursor:
    """Opaque pagination cursor representing a point in the run history."""

    before_id: str
    before_created_at: datetime

    def serialise(self) -> Mapping[str, Any]:
        return {
            "before_id": self.before_id,
            "before_created_at": self.before_created_at.astimezone(
                timezone.utc
            ).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PipelineRunPage:
    """A page of pipeline runs accompanied by pagination metadata."""

    runs: list["PipelineRun"]
    next_cursor: PipelineRunCursor | None = None

    def serialise(self) -> Mapping[str, Any]:
        return {
            "runs": [run.serialise() for run in self.runs],
            "next_cursor": (
                self.next_cursor.serialise() if self.next_cursor is not None else None
            ),
        }


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
    submitted_by: str | None = None
    roles: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))
        object.__setattr__(self, "definition_snapshot", dict(self.definition_snapshot))
        if self.metrics is None:
            object.__setattr__(self, "metrics", {})
        else:
            object.__setattr__(self, "metrics", dict(self.metrics))
        submitted_by = self.submitted_by
        if submitted_by is not None:
            text = str(submitted_by).strip()
            object.__setattr__(self, "submitted_by", text or None)
        roles: tuple[str, ...]
        if self.roles:
            seen: set[str] = set()
            normalised: list[str] = []
            for role in self.roles:
                text = str(role).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                normalised.append(text)
            roles = tuple(sorted(normalised))
        else:
            roles = ()
        object.__setattr__(self, "roles", roles)

    def serialise(self) -> Mapping[str, Any]:
        timing: dict[str, Any] = {
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_ms": self.duration_ms,
        }

        def _as_int(value: Any) -> int | None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        totals = (
            self.metrics.get("totals", {}) if isinstance(self.metrics, dict) else {}
        )
        if "step_duration_ms" in totals:
            timing["total_step_duration_ms"] = totals.get("step_duration_ms")

        queue_totals = totals.get("queue_wait")
        if isinstance(queue_totals, Mapping):
            total_wait_value = _as_int(queue_totals.get("total_ms"))
            count_value = _as_int(queue_totals.get("count"))
            last_wait_value = _as_int(queue_totals.get("last_wait_ms"))
            min_wait_value = _as_int(queue_totals.get("min_ms"))
            max_wait_value = _as_int(queue_totals.get("max_ms"))
            if total_wait_value is not None:
                timing["total_queue_wait_ms"] = total_wait_value
            if count_value is not None:
                timing["queue_wait_count"] = count_value
                if count_value:
                    if total_wait_value is not None:
                        timing["average_queue_wait_ms"] = total_wait_value / count_value
                    if min_wait_value is not None:
                        timing["min_queue_wait_ms"] = min_wait_value
                    if max_wait_value is not None:
                        timing["max_queue_wait_ms"] = max_wait_value
            if last_wait_value is not None:
                timing["last_queue_wait_ms"] = last_wait_value

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
            "submitted_by": self.submitted_by,
            "roles": list(self.roles),
        }


@dataclass(slots=True)
class PipelineRunEvent:
    """A single status update emitted for a pipeline run."""

    event_id: int | None
    run_id: str
    pipeline: str
    status: str
    timestamp: datetime
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        object.__setattr__(self, "parameters", dict(self.parameters))

    def serialise(self) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "parameters": dict(self.parameters),
        }
        if self.event_id is not None:
            payload["event_id"] = self.event_id
        return payload


@dataclass(slots=True)
class _RunEventSubscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue[PipelineRunEvent | None]


@dataclass(frozen=True, slots=True)
class PipelineRetentionPolicy:
    """Constraints applied when pruning historical pipeline runs."""

    max_age: timedelta | None = None
    max_runs: int | None = None
    max_runs_per_pipeline: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        if self.max_age is not None and self.max_age.total_seconds() < 0:
            msg = "retention max_age must be non-negative"
            raise ValueError(msg)
        if self.max_runs is not None and self.max_runs < 0:
            msg = "retention max_runs must be non-negative"
            raise ValueError(msg)
        mapping: Mapping[str, int] = self.max_runs_per_pipeline
        if mapping:
            normalised: dict[str, int] = {}
            for name, raw_value in mapping.items():
                limit = int(raw_value)
                if limit < 0:
                    msg = "retention max_runs per pipeline must be non-negative"
                    raise ValueError(msg)
                normalised[str(name)] = limit
            object.__setattr__(self, "max_runs_per_pipeline", normalised)
        else:
            object.__setattr__(self, "max_runs_per_pipeline", {})

    @property
    def configured(self) -> bool:
        return (
            self.max_age is not None
            or self.max_runs is not None
            or bool(self.max_runs_per_pipeline)
        )

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

        pipelines_raw = payload.get("pipelines")
        per_pipeline: dict[str, int] = {}
        if pipelines_raw is not None:
            if not isinstance(pipelines_raw, Mapping):
                msg = "retention pipelines configuration must be a mapping"
                raise TypeError(msg)
            for raw_name, raw_config in pipelines_raw.items():
                name = str(raw_name)
                if isinstance(raw_config, Mapping):
                    raw_limit = raw_config.get("max_runs")
                else:
                    raw_limit = raw_config
                if raw_limit is None:
                    continue
                try:
                    limit = int(raw_limit)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "retention pipeline max_runs must be an integer"
                    ) from exc
                if limit < 0:
                    raise ValueError("retention pipeline max_runs must be non-negative")
                per_pipeline[name] = limit

        policy = cls(
            max_age=max_age,
            max_runs=max_runs,
            max_runs_per_pipeline=per_pipeline,
        )
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
    removed_runs_by_pipeline: Mapping[str, int] = field(default_factory=dict)

    def serialise(self) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "removed_runs": self.removed_runs,
            "removed_events": self.removed_events,
            "remaining_runs": self.remaining_runs,
            "max_runs": self.max_runs,
            "removed_runs_by_pipeline": dict(self.removed_runs_by_pipeline),
        }
        payload["max_age_seconds"] = (
            int(self.max_age.total_seconds()) if self.max_age is not None else None
        )
        return payload
