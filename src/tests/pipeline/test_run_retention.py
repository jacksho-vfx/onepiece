from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.trafalgar.pipeline import (
    PipelineOrchestrator,
    PipelineRetentionPolicy,
    PipelineRun,
    PipelineRunEvent,
    PipelineRunStore,
)


def _create_run(
    store: PipelineRunStore,
    *,
    run_id: str,
    pipeline: str,
    status: str,
    created_at: datetime,
) -> None:
    store.create_run(
        PipelineRun(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            created_at=created_at,
            updated_at=created_at,
            parameters={},
            definition_snapshot={"name": pipeline, "steps": []},
        ),
        PipelineRunEvent(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            timestamp=created_at,
            parameters={},
        ),
    )
    store.append_event(
        run_id,
        status="succeeded",
        timestamp=created_at + timedelta(minutes=5),
        parameters={},
        run_status="succeeded",
    )


def test_store_prune_removes_old_runs_and_events(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = PipelineRunStore(database=database)
    base = datetime(2024, 3, 20, 12, tzinfo=timezone.utc)

    _create_run(
        store,
        run_id="run-1",
        pipeline="render",
        status="succeeded",
        created_at=base - timedelta(days=3),
    )
    _create_run(
        store,
        run_id="run-2",
        pipeline="render",
        status="succeeded",
        created_at=base - timedelta(days=1, hours=6),
    )
    _create_run(
        store,
        run_id="run-3",
        pipeline="render",
        status="succeeded",
        created_at=base - timedelta(hours=4),
    )

    before_runs = store._connection.execute(
        "SELECT COUNT(*) FROM pipeline_runs"
    ).fetchone()[0]
    before_events = store._connection.execute(
        "SELECT COUNT(*) FROM pipeline_run_events"
    ).fetchone()[0]
    assert before_runs == 3
    assert before_events == 6

    result = store.prune(
        max_age=timedelta(days=2),
        max_runs=1,
        now=base,
    )

    assert result.removed_runs == 2
    assert result.removed_events == 4
    assert result.remaining_runs == 1

    remaining_runs = store.list_runs()
    assert [run.run_id for run in remaining_runs] == ["run-3"]

    events = list(store.iter_run_events("run-3"))
    assert [event.status for event in events] == ["succeeded", "succeeded"]

    with pytest.raises(KeyError):
        list(store.iter_run_events("run-1"))

    after_events = store._connection.execute(
        "SELECT COUNT(*) FROM pipeline_run_events"
    ).fetchone()[0]
    assert after_events == 2


def test_orchestrator_prune_uses_retention(tmp_path: Path) -> None:
    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    policy = PipelineRetentionPolicy(max_age=timedelta(days=1), max_runs=1)
    orchestrator = PipelineOrchestrator(store=store, retention=policy)

    base = datetime(2024, 4, 1, 9, tzinfo=timezone.utc)
    _create_run(
        store,
        run_id="run-old",
        pipeline="render",
        status="succeeded",
        created_at=base - timedelta(days=2),
    )
    _create_run(
        store,
        run_id="run-new",
        pipeline="render",
        status="succeeded",
        created_at=base - timedelta(hours=2),
    )

    result = orchestrator.prune_history(now=base)

    assert result.removed_runs == 1
    assert result.remaining_runs == 1
    assert result.max_age == policy.max_age
    assert result.max_runs == policy.max_runs

    runs = store.list_runs()
    assert [run.run_id for run in runs] == ["run-new"]
