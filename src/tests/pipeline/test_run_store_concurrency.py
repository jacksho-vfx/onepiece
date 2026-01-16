"""Concurrency checks for the SQLite-backed pipeline run store."""

from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from apps.trafalgar.pipeline import PipelineRun, PipelineRunEvent, PipelineRunStore


def test_run_store_uses_wal_and_busy_timeout(tmp_path: Path) -> None:
    database = tmp_path / "runs.sqlite3"
    store = PipelineRunStore(database=database)

    mode = store._connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"

    timeout_ms = store._connection.execute("PRAGMA busy_timeout").fetchone()[0]
    expected_timeout = int(PipelineRunStore.DEFAULT_BUSY_TIMEOUT_SECONDS * 1000)
    assert timeout_ms == expected_timeout

    # Hold a write transaction open from another connection so the store needs to
    # wait for the lock to clear rather than raising an OperationalError.
    locker = sqlite3.connect(str(database))
    locker.execute("PRAGMA journal_mode=WAL")
    locker.execute("BEGIN IMMEDIATE")

    synchroniser = threading.Barrier(2)
    errors: list[BaseException] = []

    now = datetime.now(timezone.utc)
    run = PipelineRun(
        run_id="wal-demo",
        pipeline="demo",
        status="queued",
        created_at=now,
        updated_at=now,
        parameters={},
        definition_snapshot={},
    )
    event = PipelineRunEvent(
        event_id=None,
        run_id="wal-demo",
        pipeline="demo",
        status="queued",
        timestamp=now,
        parameters={},
    )

    def insert_run() -> None:
        synchroniser.wait()
        try:
            store.create_run(run, event)
        except BaseException as exc:  # pragma: no cover - failures reported below
            errors.append(exc)

    worker = threading.Thread(target=insert_run)
    worker.start()
    synchroniser.wait()
    time.sleep(0.05)
    locker.commit()
    worker.join(timeout=5)
    locker.close()

    assert not worker.is_alive(), "worker thread did not finish"
    assert not errors

    persisted = store.get_run(run.run_id)
    assert persisted.status == "queued"
