"""Tests covering stats and worker metrics commands."""

from __future__ import annotations

import json

from pytest import MonkeyPatch

from apps.onepiece.app import app as onepiece_app
from apps.onepiece.pipeline.clients import PipelineClientError
from tests.cli.pipeline.conftest import (
    StubPipelineClient,
    install_stub_pipeline_client,
    runner,
)


def test_pipeline_stats_displays_results(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        stats_payload={
            "pipelines": {
                "render": {
                    "succeeded": {
                        "count": 10,
                        "duration_seconds": {"min": 60, "max": 360, "avg": 120},
                    },
                    "failed": {"count": 2},
                }
            }
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "stats",
            "--since",
            "2024-01-01T00:00:00+00:00",
            "--include-durations",
            "--pipeline",
            "render",
        ],
    )

    assert result.exit_code == 0
    assert "render" in result.output
    assert "succeeded: 10 runs" in result.output
    assert "failed: 2 runs" in result.output
    assert client.stats_kwargs == {
        "since": "2024-01-01T00:00:00+00:00",
        "include_durations": True,
        "pipeline": "render",
    }
    assert client.closed is True


def test_pipeline_stats_handles_empty(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(stats_payload={"pipelines": {}})
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "stats"])

    assert result.exit_code == 0
    assert "No pipeline run statistics available." in result.output
    assert client.closed is True


def test_pipeline_stats_json(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "pipelines": {
            "render": {"succeeded": {"count": 10}},
        }
    }
    client = StubPipelineClient(stats_payload=payload)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "stats", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.closed is True


def test_pipeline_workers_displays_metrics(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        worker_metrics_payload={"max_workers": 6, "active_workers": 2}
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "workers"])

    assert result.exit_code == 0
    assert "Active workers: 2 (limit: 6)." in result.output
    assert client.worker_metrics_requested is True


def test_pipeline_workers_supports_json(monkeypatch: MonkeyPatch) -> None:
    payload = {"max_workers": None, "active_workers": 1}
    client = StubPipelineClient(worker_metrics_payload=payload)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "workers", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.worker_metrics_requested is True


def test_pipeline_workers_handles_errors(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("boom", status_code=500)
    client = StubPipelineClient(worker_metrics_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "workers"])

    assert result.exit_code == 1
    assert "Pipeline request failed: boom" in result.output
    assert client.worker_metrics_requested is True
