"""Regression tests for pipeline run event watchers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from apps.trafalgar.pipeline import PipelineRun, PipelineRunEvent, PipelineRunStore


@pytest.mark.asyncio
async def test_watch_run_events_terminates_after_close() -> None:
    store = PipelineRunStore()
    run_id = "run-close"
    now = datetime.now(timezone.utc)
    run = PipelineRun(
        run_id=run_id,
        pipeline="demo",
        status="queued",
        created_at=now,
        updated_at=now,
    )
    event = PipelineRunEvent(
        run_id=run_id,
        pipeline="demo",
        status="queued",
        timestamp=now,
    )
    store.create_run(run, event)

    events: list[PipelineRunEvent] = []

    async def consume() -> None:
        async for item in store.watch_run_events(run_id):
            events.append(item)

    task = asyncio.create_task(consume())
    try:
        await asyncio.sleep(0)
        store.close()
        await asyncio.wait_for(task, timeout=1)
    finally:
        store.close()

    assert [item.status for item in events] == ["queued"]


@pytest.mark.asyncio
async def test_watch_run_events_terminates_after_prune() -> None:
    store = PipelineRunStore()
    run_id = "run-prune"
    now = datetime.now(timezone.utc)
    run = PipelineRun(
        run_id=run_id,
        pipeline="demo",
        status="queued",
        created_at=now,
        updated_at=now,
    )
    event = PipelineRunEvent(
        run_id=run_id,
        pipeline="demo",
        status="queued",
        timestamp=now,
    )
    store.create_run(run, event)

    events: list[PipelineRunEvent] = []

    async def consume() -> None:
        async for item in store.watch_run_events(run_id):
            events.append(item)

    task = asyncio.create_task(consume())
    try:
        await asyncio.sleep(0)
        result = store.prune(max_runs=0)
        assert result.removed_runs == 1
        await asyncio.wait_for(task, timeout=1)
    finally:
        store.close()

    assert [item.status for item in events] == ["queued"]
