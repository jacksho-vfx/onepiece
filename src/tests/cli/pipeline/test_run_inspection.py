"""Tests covering inspecting existing pipeline runs via the CLI."""

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


def test_pipeline_run_status_displays_run(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_metadata={
            "id": "run-1",
            "pipeline": "orchestration.daily",
            "status": "running",
            "created_at": "2024-01-01T10:00:00+00:00",
            "updated_at": "2024-01-01T10:05:00+00:00",
            "parameters": {},
            "submitted_by": "suite",
            "roles": ["pipeline:run", "pipeline:manage"],
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run-status", "run-1"])

    assert result.exit_code == 0
    assert "Run run-1" in result.output
    assert "Status: running" in result.output
    assert "Submitted by: suite" in result.output
    assert client.requested_run_id == "run-1"
    assert client.closed is True


def test_pipeline_run_status_json(monkeypatch: MonkeyPatch) -> None:
    payload = {"id": "run-1", "status": "running"}
    client = StubPipelineClient(run_metadata=payload)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "run-status", "run-1", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.requested_run_id == "run-1"
    assert client.closed is True


def test_pipeline_run_status_missing(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Run not found", status_code=404)
    client = StubPipelineClient(run_status_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run-status", "run-1"])

    assert result.exit_code == 2
    assert "Run not found" in result.output
    assert client.closed is True


def test_pipeline_run_events_displays_history(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_events_history=[
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "running",
                "timestamp": "2024-01-01T10:05:00+00:00",
            },
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "succeeded",
                "timestamp": "2024-01-01T10:10:00+00:00",
            },
        ]
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run-events", "run-1"])

    assert result.exit_code == 0
    assert "[2024-01-01T10:05:00+00:00] orchestration.daily - running" in result.output
    assert (
        "[2024-01-01T10:10:00+00:00] orchestration.daily - succeeded" in result.output
    )
    assert client.requested_run_id == "run-1"
    assert client.closed is True


def test_pipeline_run_events_json(monkeypatch: MonkeyPatch) -> None:
    payload = [
        {"id": "run-1", "status": "running"},
        {"id": "run-1", "status": "succeeded"},
    ]
    client = StubPipelineClient(run_events_history=payload)  # type: ignore[arg-type]
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "run-events", "run-1", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.requested_run_id == "run-1"
    assert client.closed is True


def test_pipeline_run_events_missing(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Run not found", status_code=404)
    client = StubPipelineClient(run_events_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run-events", "run-1"])

    assert result.exit_code == 2
    assert "Run not found" in result.output
    assert client.closed is True


def test_pipeline_run_events_empty_history(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(run_events_history=[])
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run-events", "run-1"])

    assert result.exit_code == 0
    assert "No events recorded for run 'run-1'." in result.output
    assert client.requested_run_id == "run-1"
    assert client.closed is True


def test_pipeline_watch_streams_events(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_events=[
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "running",
                "timestamp": "2024-01-01T10:05:00+00:00",
            },
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "succeeded",
                "timestamp": "2024-01-01T10:10:00+00:00",
            },
        ]
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "watch", "run-1"])

    assert result.exit_code == 0
    assert "[2024-01-01T10:05:00+00:00] orchestration.daily - running" in result.output
    assert (
        "[2024-01-01T10:10:00+00:00] orchestration.daily - succeeded" in result.output
    )
    assert client.requested_run_id == "run-1"
    assert client.closed is True


def test_pipeline_watch_displays_step_metadata(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_events=[
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "step_running",
                "timestamp": "2024-01-01T10:05:30+00:00",
                "parameters": {
                    "step": "ingest",
                    "event": {
                        "name": "asset.uploaded",
                        "payload": {"asset_id": "asset-123", "retry": False},
                    },
                },
            },
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "succeeded",
                "timestamp": "2024-01-01T10:10:00+00:00",
            },
        ]
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "watch", "run-1"])

    assert result.exit_code == 0
    assert "Step: ingest" in result.output
    assert "Trigger event: asset.uploaded" in result.output
    assert 'Trigger payload: {"asset_id": "asset-123", "retry": false}' in result.output


def test_pipeline_watch_surfaces_failure_error(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_events=[
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "failed",
                "timestamp": "2024-01-01T10:10:00+00:00",
                "parameters": {
                    "error": "step ingest failed",
                    "error_message": "step ingest failed",
                    "error_type": "RuntimeError",
                    "traceback": "Traceback (most recent call last):\nRuntimeError: step ingest failed\n",
                },
            }
        ]
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "watch", "run-1"])

    assert result.exit_code == 0
    assert "failed" in result.output
    assert "Error: step ingest failed (RuntimeError)" in result.output
    assert "Traceback:" in result.output
    assert "RuntimeError: step ingest failed" in result.output


def test_pipeline_watch_missing_run(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Run not found", status_code=404)
    client = StubPipelineClient(watch_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "watch", "run-1"])

    assert result.exit_code == 2
    assert "Run not found" in result.output
    assert client.closed is True
