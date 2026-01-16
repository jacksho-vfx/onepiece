"""Tests covering pruning pipeline run history."""

from __future__ import annotations

import json
from typing import Any

from pytest import MonkeyPatch

from apps.onepiece.app import app as onepiece_app
from apps.onepiece.pipeline.clients import PipelineClientError
from tests.cli.pipeline.conftest import (
    StubPipelineClient,
    install_stub_pipeline_client,
    runner,
)


def test_pipeline_prune_forwards_overrides(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        prune_result={
            "removed_runs": 3,
            "removed_events": 12,
            "remaining_runs": 7,
            "max_age_seconds": 7200,
            "max_runs": 100,
            "removed_runs_by_pipeline": {"alpha": 2, "beta": 1},
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "prune",
            "--max-age-hours",
            "2",
            "--max-runs",
            "100",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Removed 3 runs and 12 events" in result.output
    assert "7 runs remain after pruning." in result.output
    assert "Per-pipeline removals: alpha: 2, beta: 1." in result.output
    assert "Retention applied: max age 2.00 hours, max runs 100." in result.output
    assert client.prune_kwargs == {"max_age_hours": 2.0, "max_runs": 100}
    assert client.closed is True


def test_pipeline_prune_json(monkeypatch: MonkeyPatch) -> None:
    payload: dict[str, int | None | dict[Any, Any]] = {
        "removed_runs": 1,
        "removed_events": 0,
        "remaining_runs": 5,
        "max_age_seconds": None,
        "max_runs": None,
        "removed_runs_by_pipeline": {},
    }
    client = StubPipelineClient(prune_result=payload)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "prune", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.prune_kwargs == {"max_age_hours": None, "max_runs": None}
    assert client.closed is True


def test_pipeline_prune_error(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("boom", status_code=500)
    client = StubPipelineClient(prune_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "prune"])

    assert result.exit_code == 1
    assert "Pipeline request failed: boom" in result.output
    assert client.closed is True
