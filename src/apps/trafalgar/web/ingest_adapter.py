"""Adapters for summarising ingest runs for the Trafalgar dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .ingest import IngestRunService

RECENT_RUN_LIMIT = 10


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            timestamp = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return timestamp.astimezone(timezone.utc)


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _invalid_count(run: Mapping[str, Any]) -> int:
    report = run.get("report")
    if isinstance(report, Mapping):
        invalid = report.get("invalid_count")
        if isinstance(invalid, int):
            return invalid
        try:
            return int(invalid)  # type: ignore[arg-type]
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return 0
    return 0


def _is_success(run: Mapping[str, Any]) -> bool:
    if run.get("status") != "completed":
        return False
    return _invalid_count(run) == 0


def _is_failure(run: Mapping[str, Any]) -> bool:
    if run.get("status") != "completed":
        return False
    return _invalid_count(run) > 0


class IngestRunDashboardFacade:
    """Summarise ingest runs for consumption by dashboard endpoints."""

    def __init__(self, service: IngestRunService | None = None) -> None:
        self._service = service or IngestRunService()

    def summarise_recent_runs(self, limit: int = RECENT_RUN_LIMIT) -> dict[str, Any]:
        runs = self._service.list_runs(limit)
        return self._summarise_runs(runs)

    def _summarise_runs(self, runs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        successes = [_parse_timestamp(run.get("completed_at")) for run in runs if _is_success(run)]
        successes = [timestamp for timestamp in successes if timestamp is not None]
        last_success = max(successes) if successes else None

        failure_streak = 0
        for run in runs:
            if _is_success(run):
                break
            if _is_failure(run):
                failure_streak += 1
                continue
            break

        summary = {
            "counts": {
                "total": len(runs),
                "successful": sum(1 for run in runs if _is_success(run)),
                "failed": sum(1 for run in runs if _is_failure(run)),
                "running": sum(1 for run in runs if run.get("status") == "running"),
            },
            "last_success_at": _format_timestamp(last_success),
            "failure_streak": failure_streak,
        }
        return summary


def get_ingest_dashboard_facade() -> IngestRunDashboardFacade:  # pragma: no cover - runtime wiring
    return IngestRunDashboardFacade()
