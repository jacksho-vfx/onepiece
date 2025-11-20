from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.trafalgar.pipeline import PipelineRunStore


def _insert_run(
    store: PipelineRunStore,
    *,
    run_id: str,
    parameters: str = "{}",
    definition_snapshot: str = "{}",
    metrics: str = "{}",
    created_at: datetime | None = None,
) -> None:
    timestamp = created_at or datetime.now(timezone.utc)
    encoded = store._encode_datetime(timestamp)
    with store._connection:
        store._connection.execute(
            """
            INSERT INTO pipeline_runs (
                run_id, pipeline, status, created_at, updated_at,
                parameters, definition_snapshot, started_at, finished_at,
                duration_ms, metrics, submitted_by, submitted_roles
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                "demo",
                "running",
                encoded,
                encoded,
                parameters,
                definition_snapshot,
                None,
                None,
                None,
                metrics,
                None,
                None,
            ),
        )


def test_decode_parameters_warns_on_malformed_payload(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    _insert_run(
        store,
        run_id="bad-params",
        parameters="{not json",
        definition_snapshot=json.dumps({"name": "demo"}),
    )

    with caplog.at_level(logging.WARNING):
        run = store.get_run("bad-params")

    assert run.parameters == {}
    assert any("parameters payload" in record.message for record in caplog.records)


def test_decode_definition_snapshot_warns_on_non_mapping(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    _insert_run(
        store,
        run_id="bad-snapshot",
        definition_snapshot=json.dumps(["unexpected", "list"]),
    )

    with caplog.at_level(logging.WARNING):
        run = store.get_run("bad-snapshot")

    assert run.definition_snapshot == {}
    assert any(
        "Definition snapshot payload" in record.message for record in caplog.records
    )


def test_decode_metrics_warns_on_malformed_payload(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = PipelineRunStore(database=tmp_path / "runs.sqlite3")
    _insert_run(store, run_id="bad-metrics", metrics="{{")

    with caplog.at_level(logging.WARNING):
        run = store.get_run("bad-metrics")

    assert run.metrics == PipelineRunStore._initial_metrics()
    assert any("metrics payload" in record.message for record in caplog.records)
