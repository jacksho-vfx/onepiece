from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import Mock

from apps.trafalgar.web.ingest_adapter import IngestRunDashboardFacade


def _make_run(
    status: object,
    *,
    invalid_count: int | None = 0,
    completed_at: datetime | None = None,
) -> dict[str, object]:
    run: dict[str, object] = {"status": status}
    if completed_at is not None:
        run["completed_at"] = completed_at

    report: dict[str, object] = {}
    if invalid_count is not None:
        report["invalid_count"] = invalid_count
    if report:
        run["report"] = report

    return run


def test_summarise_runs_normalises_status_counts() -> None:
    facade = IngestRunDashboardFacade(service=Mock())
    runs = [
        _make_run("COMPLETED", invalid_count=2),
        _make_run(
            "Completed",
            invalid_count=0,
            completed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
        _make_run(" RUNNING ", invalid_count=None),
        _make_run(None, invalid_count=0),
    ]

    summary = facade._summarise_runs(runs)

    assert summary["counts"] == {
        "total": 4,
        "successful": 1,
        "failed": 1,
        "running": 1,
    }
    # Failure streak should only include the leading failure even with mixed casing.
    assert summary["failure_streak"] == 1
    # The normalised success contributes the last success timestamp.
    assert summary["last_success_at"] == "2024-01-01T00:00:00+00:00"
