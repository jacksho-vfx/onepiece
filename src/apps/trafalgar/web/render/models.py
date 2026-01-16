"""Data models and helpers for render job persistence."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Collection, Mapping

from .schemas import RenderJobMetadata, RenderJobRequest

TERMINAL_STATUSES: set[str] = {
    "completed",
    "failed",
    "cancelled",
    "aborted",
    "errored",
    "error",
}


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


__all__ = [
    "TERMINAL_STATUSES",
    "_JobRecord",
    "_parse_timestamp",
    "_serialise_datetime",
    "_utcnow",
]
