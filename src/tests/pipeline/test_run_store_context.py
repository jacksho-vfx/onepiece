from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.trafalgar.pipeline import PipelineRun, PipelineRunEvent, PipelineRunStore


def test_run_store_context_manager_closes_connection(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"

    with PipelineRunStore(database=database) as store:
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id="context-close",
            pipeline="demo",
            status="queued",
            created_at=now,
            updated_at=now,
        )
        event = PipelineRunEvent(
            event_id=None,
            run_id=run.run_id,
            pipeline=run.pipeline,
            status="queued",
            timestamp=now,
        )
        store.create_run(run, event)
        connection = store._connection

    assert store._closed is True
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


def test_run_store_enforces_foreign_key_constraints(tmp_path: Path) -> None:
    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    timestamp = datetime.now(timezone.utc)

    with pytest.raises(sqlite3.IntegrityError):
        with store._connection:
            store._connection.execute(
                """
                INSERT INTO pipeline_run_events (
                    run_id, pipeline, status, timestamp, parameters
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "missing-run",
                    "demo",
                    "queued",
                    timestamp.isoformat(),
                    "{}",
                ),
            )

    store.close()


@pytest.mark.asyncio
async def test_run_store_context_manager_notifies_watchers() -> None:
    events: list[PipelineRunEvent] = []

    async def consume(iterator: AsyncIterator[PipelineRunEvent]) -> None:
        async for item in iterator:
            events.append(item)

    with PipelineRunStore() as store:
        now = datetime.now(timezone.utc)
        run = PipelineRun(
            run_id="context-watcher",
            pipeline="demo",
            status="queued",
            created_at=now,
            updated_at=now,
        )
        event = PipelineRunEvent(
            event_id=None,
            run_id=run.run_id,
            pipeline=run.pipeline,
            status="queued",
            timestamp=now,
        )
        store.create_run(run, event)

        iterator = store.watch_run_events(run.run_id)
        consumer = asyncio.create_task(consume(iterator))
        await asyncio.sleep(0)

    await asyncio.wait_for(consumer, timeout=1)
    assert [item.status for item in events] == ["queued"]
