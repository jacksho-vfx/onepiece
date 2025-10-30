from datetime import datetime, timedelta, timezone
import time
from pathlib import Path
import pytest
from typing import Any

from apps.trafalgar.pipeline import (
    PipelineDefinition,
    PipelineOrchestrator,
    PipelineRetentionPolicy,
    PipelineRun,
    PipelineRunEvent,
    PipelineRunStore,
)
from libraries.pipeline.models import Pipeline, PipelineStep


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


def _wait_for_completion(
    orchestrator: PipelineOrchestrator, run_id: str, *, timeout: float = 5.0
) -> PipelineRun:
    deadline = time.monotonic() + timeout
    while True:
        run = orchestrator.get_run(run_id)
        if run.status in {"succeeded", "failed"}:
            return run
        if time.monotonic() >= deadline:
            msg = f"timed out waiting for run '{run_id}' to complete"
            raise AssertionError(msg)
        time.sleep(0.01)


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


def test_orchestrator_prunes_runs_after_completion(tmp_path: Path) -> None:
    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    policy = PipelineRetentionPolicy(max_runs=2)

    class _NoOpExecutor:
        def resolve_pipeline(self, pipeline: Pipeline) -> Pipeline:
            return pipeline

        def execute(
            self,
            pipeline: Pipeline,
            *,
            parameters: dict[str, object] | None,
            emit: Any,
        ) -> None:
            _ = (pipeline, parameters, emit)

    orchestrator = PipelineOrchestrator(
        store=store,
        retention=policy,
        executor=_NoOpExecutor(),
    )

    def _noop_provider(*_: object, **__: object) -> None:
        return None

    pipeline = Pipeline(
        name="demo",
        steps=[PipelineStep(name="noop", provider=_noop_provider)],
    )

    try:
        orchestrator.register(
            PipelineDefinition(
                name="demo",
                pipeline=pipeline,
                parameters={},
            )
        )

        run_ids: list[str] = []
        for _ in range(3):
            run = orchestrator.trigger_run("demo")
            run_ids.append(run.run_id)
            _wait_for_completion(orchestrator, run.run_id)

        deadline = time.monotonic() + 2.0
        remaining_ids: list[str] = []
        while time.monotonic() < deadline:
            remaining = store.list_runs()
            remaining_ids = [run.run_id for run in remaining]
            if len(remaining_ids) <= 2:
                break
            time.sleep(0.01)

        assert remaining_ids == [run_ids[-1], run_ids[-2]]
    finally:
        orchestrator.shutdown()
