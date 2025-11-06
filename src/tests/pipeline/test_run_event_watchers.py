"""Regression tests for pipeline run event watchers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

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
        event_id=None,
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
        event_id=None,
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


@pytest.mark.asyncio
async def test_watch_run_events_resumes_from_event_id() -> None:
    store = PipelineRunStore()
    run_id = "run-resume-id"
    now = datetime.now(timezone.utc)
    run = PipelineRun(
        run_id=run_id,
        pipeline="demo",
        status="queued",
        created_at=now,
        updated_at=now,
    )
    initial_event = PipelineRunEvent(
        event_id=None,
        run_id=run_id,
        pipeline="demo",
        status="queued",
        timestamp=now,
    )
    store.create_run(run, initial_event)
    running_event_time = now + timedelta(seconds=1)
    store.append_event(
        run_id,
        status="running",
        timestamp=running_event_time,
        parameters={},
        run_status="running",
    )
    store.append_event(
        run_id,
        status="succeeded",
        timestamp=running_event_time + timedelta(seconds=1),
        parameters={},
        run_status="succeeded",
    )

    recorded = list(store.iter_run_events(run_id))
    first_id = recorded[0].event_id
    assert first_id is not None

    statuses: list[str] = []

    async def consume() -> None:
        async for item in store.watch_run_events(run_id, after_event_id=first_id):
            statuses.append(item.status)
            if item.status in {"succeeded", "failed"}:
                break

    await consume()
    store.close()

    assert statuses == ["running", "succeeded"]


@pytest.mark.asyncio
async def test_watch_run_events_resumes_from_timestamp() -> None:
    store = PipelineRunStore()
    run_id = "run-resume-ts"
    now = datetime.now(timezone.utc)
    run = PipelineRun(
        run_id=run_id,
        pipeline="demo",
        status="queued",
        created_at=now,
        updated_at=now,
    )
    initial_event = PipelineRunEvent(
        event_id=None,
        run_id=run_id,
        pipeline="demo",
        status="queued",
        timestamp=now,
    )
    store.create_run(run, initial_event)

    running_event_time = now + timedelta(seconds=1)
    store.append_event(
        run_id,
        status="running",
        timestamp=running_event_time,
        parameters={},
        run_status="running",
    )
    succeeded_time = running_event_time + timedelta(seconds=1)
    store.append_event(
        run_id,
        status="succeeded",
        timestamp=succeeded_time,
        parameters={},
        run_status="succeeded",
    )

    recorded = list(store.iter_run_events(run_id))
    cursor_timestamp = recorded[0].timestamp

    statuses: list[str] = []

    async def consume() -> None:
        async for item in store.watch_run_events(
            run_id, since_timestamp=cursor_timestamp
        ):
            statuses.append(item.status)
            if item.status in {"succeeded", "failed"}:
                break

    await consume()
    store.close()

    assert statuses == ["running", "succeeded"]
