from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from apps.trafalgar.app import pipeline_history
from apps.trafalgar.pipeline import (
    PipelineOrchestrator,
    PipelineRun,
    PipelineRunEvent,
    set_pipeline_orchestrator,
)


@pytest.fixture
def orchestrator() -> PipelineOrchestrator:
    orchestrator = PipelineOrchestrator()
    set_pipeline_orchestrator(orchestrator)
    try:
        yield orchestrator
    finally:
        set_pipeline_orchestrator(None)


def _add_run(
    orchestrator: PipelineOrchestrator,
    *,
    run_id: str,
    pipeline: str,
    status: str,
    created_at: datetime,
    finished_at: datetime | None = None,
    duration_ms: int | None = None,
) -> None:
    run = PipelineRun(
        run_id=run_id,
        pipeline=pipeline,
        status=status,
        created_at=created_at,
        updated_at=finished_at or created_at,
        parameters={},
        definition_snapshot={},
        started_at=created_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
    )
    event = PipelineRunEvent(
        event_id=None,
        run_id=run_id,
        pipeline=pipeline,
        status=status,
        timestamp=created_at,
        parameters={},
    )
    orchestrator._store.create_run(run, event)


def test_history_formats_runs_by_pipeline(
    orchestrator: PipelineOrchestrator, capsys: pytest.CaptureFixture[str]
) -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    _add_run(
        orchestrator,
        run_id="alpha-1",
        pipeline="alpha",
        status="succeeded",
        created_at=base,
        finished_at=base + timedelta(seconds=2),
        duration_ms=2000,
    )
    _add_run(
        orchestrator,
        run_id="alpha-2",
        pipeline="alpha",
        status="failed",
        created_at=base + timedelta(days=1),
        finished_at=base + timedelta(days=1, seconds=3),
        duration_ms=3000,
    )
    _add_run(
        orchestrator,
        run_id="beta-1",
        pipeline="beta",
        status="succeeded",
        created_at=base + timedelta(days=2),
        finished_at=base + timedelta(days=2, seconds=4),
        duration_ms=4000,
    )

    pipeline_history()

    output = capsys.readouterr().out.strip().splitlines()

    assert output == [
        "Pipeline: alpha",
        "  alpha-2 [failed] | created 2024-01-02T00:00:00+00:00 | finished 2024-01-02T00:00:03+00:00 | duration 3.00s",
        "  alpha-1 [succeeded] | created 2024-01-01T00:00:00+00:00 | finished 2024-01-01T00:00:02+00:00 | duration 2.00s",
        "Pipeline: beta",
        "  beta-1 [succeeded] | created 2024-01-03T00:00:00+00:00 | finished 2024-01-03T00:00:04+00:00 | duration 4.00s",
    ]


def test_history_serialises_runs_as_json(
    orchestrator: PipelineOrchestrator, capsys: pytest.CaptureFixture[str]
) -> None:
    created_at = datetime(2024, 2, 1, 12, 30, tzinfo=timezone.utc)
    _add_run(
        orchestrator,
        run_id="gamma-1",
        pipeline="gamma",
        status="running",
        created_at=created_at,
        duration_ms=1500,
    )

    pipeline_history(limit=1, pipeline=" gamma ", format="json")

    payload = json.loads(capsys.readouterr().out)

    assert payload["runs"]
    first = payload["runs"][0]
    assert first["id"] == "gamma-1"
    assert first["pipeline"] == "gamma"
    assert first["status"] == "running"
    assert payload["next_cursor"] is None
