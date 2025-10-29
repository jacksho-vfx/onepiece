"""Tests for pipeline run listing functionality."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_list_runs_orders_descending_by_creation() -> None:
    store = PipelineRunStore()
    _seed_runs(store)

    runs = store.list_runs()

    assert [run.run_id for run in runs] == ["run-3", "run-2", "run-1"]


def test_list_runs_supports_filters_and_limit() -> None:
    store = PipelineRunStore()
    seeded = _seed_runs(store)

    render_runs = store.list_runs(pipeline="render_shots")
    assert [run.run_id for run in render_runs] == ["run-2", "run-1"]

    failed_runs = store.list_runs(status="failed")
    assert [run.run_id for run in failed_runs] == ["run-2"]

    since_timestamp = seeded[1].created_at
    recent_runs = store.list_runs(since=since_timestamp)
    assert [run.run_id for run in recent_runs] == ["run-3", "run-2"]

    limited = store.list_runs(limit=1)
    assert [run.run_id for run in limited] == ["run-3"]


def test_orchestrator_list_runs_proxies_store() -> None:
    store = PipelineRunStore()
    _seed_runs(store)
    orchestrator = PipelineOrchestrator(store=store)

    runs = orchestrator.list_runs(limit=2)

    assert [run.run_id for run in runs] == ["run-3", "run-2"]
