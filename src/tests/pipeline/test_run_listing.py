"""Tests for pipeline run listing functionality."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from apps.trafalgar.pipeline import (
    PipelineOrchestrator,
    PipelineRun,
    PipelineRunEvent,
    PipelineRunStore,
)


def _seed_runs(store: PipelineRunStore) -> list[PipelineRun]:
    base = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    seeded: list[PipelineRun] = []
    runs = [
        ("run-1", "render_shots", "succeeded", 0),
        ("run-2", "render_shots", "failed", 1),
        ("run-3", "publish_assets", "succeeded", 2),
    ]
    for run_id, pipeline, status, offset in runs:
        created = base + timedelta(hours=offset)
        run = PipelineRun(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            created_at=created,
            updated_at=created,
            parameters={},
            definition_snapshot={"name": pipeline, "steps": []},
        )
        store.create_run(
            run,
            PipelineRunEvent(
                run_id=run_id,
                pipeline=pipeline,
                status=status,
                timestamp=created,
                parameters={},
            ),
        )
        seeded.append(run)
    return seeded


def _create_run(
    store: PipelineRunStore,
    *,
    run_id: str,
    pipeline: str,
    status: str,
    created_at: datetime,
    updated_at: datetime,
) -> None:
    run = PipelineRun(
        run_id=run_id,
        pipeline=pipeline,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        parameters={},
        definition_snapshot={"name": pipeline, "steps": []},
    )
    store.create_run(
        run,
        PipelineRunEvent(
            run_id=run_id,
            pipeline=pipeline,
            status=status,
            timestamp=created_at,
            parameters={},
        ),
    )


def _create_queued_run(
    store: PipelineRunStore,
    *,
    run_id: str,
    pipeline: str,
    created_at: datetime,
) -> None:
    run = PipelineRun(
        run_id=run_id,
        pipeline=pipeline,
        status="queued",
        created_at=created_at,
        updated_at=created_at,
        parameters={},
        definition_snapshot={"name": pipeline, "steps": []},
    )
    store.create_run(
        run,
        PipelineRunEvent(
            run_id=run_id,
            pipeline=pipeline,
            status="queued",
            timestamp=created_at,
            parameters={},
        ),
    )


def test_list_runs_orders_descending_by_creation() -> None:
    store = PipelineRunStore()
    _seed_runs(store)

    page = store.list_runs()

    assert [run.run_id for run in page.runs] == ["run-3", "run-2", "run-1"]


def test_list_runs_supports_filters_and_limit() -> None:
    store = PipelineRunStore()
    seeded = _seed_runs(store)

    render_runs = store.list_runs(pipeline="render_shots")
    assert [run.run_id for run in render_runs.runs] == ["run-2", "run-1"]

    failed_runs = store.list_runs(status="failed")
    assert [run.run_id for run in failed_runs.runs] == ["run-2"]

    since_timestamp = seeded[1].created_at
    recent_runs = store.list_runs(since=since_timestamp)
    assert [run.run_id for run in recent_runs.runs] == ["run-3", "run-2"]

    limited = store.list_runs(limit=1)
    assert [run.run_id for run in limited.runs] == ["run-3"]


def test_list_runs_paginates_with_cursors() -> None:
    store = PipelineRunStore()
    base = datetime(2024, 4, 1, 12, tzinfo=timezone.utc)
    for index in range(5):
        created = base + timedelta(hours=index)
        _create_run(
            store,
            run_id=f"run-{index}",
            pipeline="render",
            status="succeeded",
            created_at=created,
            updated_at=created,
        )

    first_page = store.list_runs(limit=2)
    assert [run.run_id for run in first_page.runs] == ["run-4", "run-3"]
    assert first_page.next_cursor is not None

    second_page = store.list_runs(
        limit=2,
        before_id=first_page.next_cursor.before_id,
        before_created_at=first_page.next_cursor.before_created_at,
    )
    assert [run.run_id for run in second_page.runs] == ["run-2", "run-1"]
    assert second_page.next_cursor is not None

    final_page = store.list_runs(
        limit=2,
        before_id=second_page.next_cursor.before_id,
        before_created_at=second_page.next_cursor.before_created_at,
    )
    assert [run.run_id for run in final_page.runs] == ["run-0"]
    assert final_page.next_cursor is None


def test_orchestrator_list_runs_proxies_store() -> None:
    store = PipelineRunStore()
    _seed_runs(store)
    orchestrator = PipelineOrchestrator(store=store)

    page = orchestrator.list_runs(limit=2)

    assert [run.run_id for run in page.runs] == ["run-3", "run-2"]


def test_aggregate_runs_groups_statistics() -> None:
    store = PipelineRunStore()
    base = datetime(2024, 2, 1, 10, tzinfo=timezone.utc)
    _create_run(
        store,
        run_id="run-1",
        pipeline="render",
        status="succeeded",
        created_at=base,
        updated_at=base + timedelta(minutes=5),
    )
    _create_run(
        store,
        run_id="run-2",
        pipeline="render",
        status="failed",
        created_at=base + timedelta(minutes=10),
        updated_at=base + timedelta(minutes=12),
    )
    _create_run(
        store,
        run_id="run-3",
        pipeline="publish",
        status="succeeded",
        created_at=base + timedelta(minutes=20),
        updated_at=base + timedelta(minutes=32),
    )

    stats = store.aggregate_runs()

    assert stats == {
        "publish": {"succeeded": {"count": 1}},
        "render": {
            "failed": {"count": 1},
            "succeeded": {"count": 1},
        },
    }


def test_aggregate_runs_optionally_includes_durations() -> None:
    store = PipelineRunStore()
    base = datetime(2024, 3, 1, 9, tzinfo=timezone.utc)
    _create_run(
        store,
        run_id="run-1",
        pipeline="render",
        status="succeeded",
        created_at=base,
        updated_at=base + timedelta(seconds=30),
    )
    _create_run(
        store,
        run_id="run-2",
        pipeline="render",
        status="succeeded",
        created_at=base + timedelta(seconds=30),
        updated_at=base + timedelta(seconds=75),
    )

    stats = store.aggregate_runs(include_durations=True)

    durations = stats["render"]["succeeded"]["durations"]
    assert durations is not None
    assert durations["min_seconds"] == 30.0
    assert durations["max_seconds"] == 45.0
    assert durations["average_seconds"] == 37.5


def test_aggregate_runs_supports_since_filter() -> None:
    store = PipelineRunStore()
    base = datetime(2024, 4, 1, 8, tzinfo=timezone.utc)
    _create_run(
        store,
        run_id="run-1",
        pipeline="render",
        status="succeeded",
        created_at=base,
        updated_at=base + timedelta(minutes=1),
    )
    _create_run(
        store,
        run_id="run-2",
        pipeline="render",
        status="failed",
        created_at=base + timedelta(minutes=2),
        updated_at=base + timedelta(minutes=3),
    )

    stats = store.aggregate_runs(since=base + timedelta(minutes=1, seconds=1))

    assert stats == {"render": {"failed": {"count": 1}}}


def test_orchestrator_aggregate_runs_proxies_store() -> None:
    store = PipelineRunStore()
    base = datetime(2024, 5, 1, 7, tzinfo=timezone.utc)
    _create_run(
        store,
        run_id="run-1",
        pipeline="render",
        status="succeeded",
        created_at=base,
        updated_at=base + timedelta(minutes=2),
    )
    orchestrator = PipelineOrchestrator(store=store)

    stats = orchestrator.aggregate_runs(include_durations=True)

    assert "render" in stats
    succeeded = stats["render"]["succeeded"]
    assert succeeded["count"] == 1
    assert succeeded["durations"]["average_seconds"] == 120.0


def test_append_event_records_queue_wait_metrics() -> None:
    store = PipelineRunStore()
    base = datetime(2024, 7, 1, 9, tzinfo=timezone.utc)
    _create_queued_run(
        store,
        run_id="run-queued",
        pipeline="render",
        created_at=base,
    )

    started = base + timedelta(seconds=12)
    store.append_event(
        "run-queued",
        status="running",
        timestamp=started,
        parameters={},
        run_status="running",
    )

    persisted = store.get_run("run-queued")
    assert persisted.started_at == started

    metrics = persisted.metrics
    assert isinstance(metrics, dict)
    totals = metrics.get("totals", {})
    assert isinstance(totals, dict)
    queue_metrics = totals.get("queue_wait", {})
    assert isinstance(queue_metrics, dict)

    assert queue_metrics.get("total_ms") == 12_000
    assert queue_metrics.get("count") == 1
    assert queue_metrics.get("last_wait_ms") == 12_000
    assert queue_metrics.get("min_ms") == 12_000
    assert queue_metrics.get("max_ms") == 12_000
    assert "last_queued_at" not in queue_metrics


def test_aggregate_runs_includes_queue_wait_statistics() -> None:
    store = PipelineRunStore()
    base = datetime(2024, 7, 2, 10, tzinfo=timezone.utc)

    _create_queued_run(
        store,
        run_id="run-success-1",
        pipeline="render",
        created_at=base,
    )
    first_start = base + timedelta(seconds=10)
    first_finish = base + timedelta(seconds=40)
    store.append_event(
        "run-success-1",
        status="running",
        timestamp=first_start,
        parameters={},
        run_status="running",
    )
    store.append_event(
        "run-success-1",
        status="succeeded",
        timestamp=first_finish,
        parameters={},
        run_status="succeeded",
    )

    later_created = base + timedelta(minutes=5)
    _create_queued_run(
        store,
        run_id="run-success-2",
        pipeline="render",
        created_at=later_created,
    )
    second_start = later_created + timedelta(seconds=25)
    second_finish = later_created + timedelta(seconds=80)
    store.append_event(
        "run-success-2",
        status="running",
        timestamp=second_start,
        parameters={},
        run_status="running",
    )
    store.append_event(
        "run-success-2",
        status="succeeded",
        timestamp=second_finish,
        parameters={},
        run_status="succeeded",
    )

    queued_created = base + timedelta(minutes=10)
    _create_queued_run(
        store,
        run_id="run-backlog",
        pipeline="render",
        created_at=queued_created,
    )

    stats = store.aggregate_runs(include_durations=True)

    succeeded = stats["render"]["succeeded"]
    waits = succeeded.get("queue_waits")
    assert waits is not None
    assert pytest.approx(waits["average_seconds"], rel=1e-3) == 17.5
    assert waits["min_seconds"] == pytest.approx(10.0)
    assert waits["max_seconds"] == pytest.approx(25.0)

    queued = stats["render"]["queued"]
    assert queued["backlog_count"] == 1
