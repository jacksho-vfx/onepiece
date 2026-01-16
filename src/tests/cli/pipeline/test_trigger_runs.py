"""Tests covering triggering pipeline runs via the CLI."""

from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from apps.onepiece.app import app as onepiece_app
from apps.onepiece.pipeline.clients import PipelineClientError
from tests.cli.pipeline.conftest import (
    StubPipelineClient,
    install_stub_pipeline_client,
    runner,
)


def test_pipeline_run_success(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_payload={
            "id": "abc123",
            "pipeline": "orchestration.daily",
            "status": "succeeded",
            "submitted_by": "suite",
            "roles": ["pipeline:run", "pipeline:manage"],
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "run",
            "orchestration.daily",
            "--param",
            "ingest_profile=episodic",
        ],
    )

    assert result.exit_code == 0
    assert "Triggered pipeline 'orchestration.daily' (run id: abc123)." in result.output
    assert "Current status: succeeded" in result.output
    assert "Initiated by: suite" in result.output
    assert "Roles: pipeline:manage, pipeline:run" in result.output
    assert client.requested_name == "orchestration.daily"
    assert client.run_parameters == {"ingest_profile": "episodic"}
    assert client.stream_requested is False
    assert client.closed is True


def test_pipeline_run_reports_disabled_pipeline(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError(
        "pipeline 'orchestration.daily' is disabled", status_code=400
    )
    client = StubPipelineClient(run_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "run", "orchestration.daily"],
    )

    assert result.exit_code == 1
    assert "pipeline 'orchestration.daily' is disabled" in result.output
    assert client.closed is True


def test_pipeline_run_parameters_from_file(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    params_path = tmp_path / "params.json"
    params_path.write_text(
        json.dumps(
            {
                "ingest_profile": "episodic",
                "notifications": {"email": True, "slack": ["alerts", "ops"]},
            }
        ),
        encoding="utf-8",
    )

    client = StubPipelineClient(
        run_payload={
            "id": "abc123",
            "pipeline": "orchestration.daily",
            "status": "queued",
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "run",
            "orchestration.daily",
            "--params-file",
            str(params_path),
            "--param",
            "ingest_profile=override",
        ],
    )

    assert result.exit_code == 0
    assert client.run_parameters == {
        "ingest_profile": "override",
        "notifications": {"email": True, "slack": ["alerts", "ops"]},
    }


def test_pipeline_run_waits_for_completion(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_payload={
            "id": "abc123",
            "pipeline": "orchestration.daily",
            "status": "queued",
        },
        run_metadata={
            "id": "abc123",
            "pipeline": "orchestration.daily",
            "status": "succeeded",
        },
        run_events=[
            {
                "timestamp": "2024-01-01T10:00:00+00:00",
                "pipeline": "orchestration.daily",
                "status": "running",
            },
            {
                "timestamp": "2024-01-01T10:05:00+00:00",
                "pipeline": "orchestration.daily",
                "status": "succeeded",
            },
        ],
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "run", "orchestration.daily", "--wait"],
    )

    assert result.exit_code == 0
    assert "Triggered pipeline 'orchestration.daily' (run id: abc123)." in result.output
    assert "Waiting for run to complete..." in result.output
    assert "[2024-01-01T10:00:00+00:00] orchestration.daily - running" in result.output
    assert (
        "[2024-01-01T10:05:00+00:00] orchestration.daily - succeeded" in result.output
    )
    assert "Run completed with status: succeeded" in result.output
    assert client.stream_requested is True
    assert client.requested_run_id == "abc123"
    assert client.closed is True


def test_pipeline_run_rejects_wait_with_json(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_payload={
            "id": "abc123",
            "pipeline": "orchestration.daily",
            "status": "queued",
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "run", "orchestration.daily", "--wait", "--format", "json"],
    )

    assert result.exit_code == 2
    terms = ["wait", "cannot", "format"]
    for term in terms:
        assert term in result.output
    assert client.requested_name is None
    assert client.closed is False


def test_pipeline_run_rejects_invalid_parameters(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_payload={"id": "abc", "pipeline": "p", "status": "queued"}
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "run", "orchestration.daily", "--param", "invalid"],
    )

    assert result.exit_code == 2
    assert "Invalid parameter 'invalid'" in result.output
    assert client.requested_name is None
    assert client.closed is False


def test_pipeline_run_missing_pipeline(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Pipeline 'missing' was not found.", status_code=404)
    client = StubPipelineClient(run_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "run",
            "missing",
            "--param",
            "ingest_profile=episodic",
        ],
    )

    assert result.exit_code == 2
    assert "Pipeline 'missing' was not found." in result.output
    assert client.closed is True


def test_pipeline_run_failure(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Service unavailable", status_code=503)
    client = StubPipelineClient(run_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run", "orchestration.daily"])

    assert result.exit_code == 1
    assert "Pipeline request failed: Service unavailable" in result.output
    assert client.closed is True


def test_pipeline_rerun_success(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        rerun_payload={
            "id": "new456",
            "pipeline": "orchestration.daily",
            "status": "running",
            "submitted_by": "suite",
            "roles": ["pipeline:run"],
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "rerun",
            "abc123",
            "--param",
            "ingest_profile=episodic",
        ],
    )

    assert result.exit_code == 0
    assert (
        "Triggered rerun for pipeline 'orchestration.daily' (run id: new456)"
        " from 'abc123'." in result.output
    )
    assert "Current status: running" in result.output
    assert "Initiated by: suite" in result.output
    assert "Roles: pipeline:run" in result.output
    assert client.rerun_run_id == "abc123"
    assert client.rerun_parameters == {"ingest_profile": "episodic"}
    assert client.closed is True


def test_pipeline_rerun_waits_for_completion(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        rerun_payload={
            "id": "new456",
            "pipeline": "orchestration.daily",
            "status": "queued",
        },
        run_events=[
            {
                "timestamp": "2024-02-01T10:00:00+00:00",
                "pipeline": "orchestration.daily",
                "status": "running",
            },
            {
                "timestamp": "2024-02-01T10:05:00+00:00",
                "pipeline": "orchestration.daily",
                "status": "succeeded",
            },
        ],
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "rerun", "abc123", "--wait"],
    )

    assert result.exit_code == 0
    assert (
        "Triggered rerun for pipeline 'orchestration.daily' (run id: new456)"
        in result.output
    )
    assert "Waiting for rerun to complete..." in result.output
    assert "[2024-02-01T10:00:00+00:00] orchestration.daily - running" in result.output
    assert (
        "[2024-02-01T10:05:00+00:00] orchestration.daily - succeeded" in result.output
    )
    assert "Run completed with status: succeeded" in result.output
    assert client.stream_requested is True
    assert client.rerun_run_id == "abc123"
    assert client.closed is True


def test_pipeline_rerun_rejects_wait_with_json(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        rerun_payload={
            "id": "new456",
            "pipeline": "orchestration.daily",
            "status": "queued",
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "rerun", "abc123", "--wait", "--format", "json"],
    )

    assert result.exit_code == 2
    assert "wait" in result.output.lower()
    assert client.rerun_run_id is None
    assert client.closed is False


def test_pipeline_rerun_missing_run(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Run not found", status_code=404)
    client = StubPipelineClient(rerun_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "rerun", "unknown"])

    assert result.exit_code == 2
    assert "Run not found" in result.output
    assert client.closed is True


def test_pipeline_rerun_failure(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Service unavailable", status_code=503)
    client = StubPipelineClient(rerun_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "rerun", "abc123"])

    assert result.exit_code == 1
    assert "Pipeline request failed: Service unavailable" in result.output
    assert client.closed is True
