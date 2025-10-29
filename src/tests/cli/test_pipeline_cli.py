"""Tests for the OnePiece pipeline CLI surface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from typer.testing import CliRunner

from apps.onepiece.app import app as onepiece_app
from apps.onepiece.pipeline import PipelineClientError


runner = CliRunner()


@dataclass
class StubPipelineClient:
    """Simple stub implementing the pipeline client protocol for tests."""

    definitions: list[Mapping[str, Any]] | None = None
    definition: Mapping[str, Any] | None = None
    run_payload: Mapping[str, Any] | None = None
    list_error: PipelineClientError | None = None
    describe_error: PipelineClientError | None = None
    run_error: PipelineClientError | None = None

    closed: bool = False
    requested_name: str | None = None
    run_parameters: Mapping[str, Any] | None = None

    def list_definitions(self) -> list[Mapping[str, Any]]:
        if self.list_error:
            raise self.list_error
        return list(self.definitions or [])

    def get_definition(self, name: str) -> Mapping[str, Any]:
        self.requested_name = name
        if self.describe_error:
            raise self.describe_error
        if self.definition is None:
            raise AssertionError("definition payload was not configured")
        return dict(self.definition)

    def trigger_run(self, name: str, parameters: Mapping[str, Any]) -> Mapping[str, Any]:
        self.requested_name = name
        self.run_parameters = dict(parameters)
        if self.run_error:
            raise self.run_error
        if self.run_payload is None:
            raise AssertionError("run payload was not configured")
        return dict(self.run_payload)

    def close(self) -> None:
        self.closed = True


def _install_stub(monkeypatch, client: StubPipelineClient) -> StubPipelineClient:
    from apps.onepiece import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "_create_pipeline_client", lambda: client)
    return client


def test_pipeline_command_group_loads() -> None:
    result = runner.invoke(onepiece_app, ["pipeline", "--help"])

    assert result.exit_code == 0
    assert "Interact with the OnePiece pipeline orchestrator." in result.output
    assert "list" in result.output
    assert "describe" in result.output
    assert "run" in result.output


def test_pipeline_list_displays_definitions(monkeypatch) -> None:
    client = StubPipelineClient(
        definitions=[
            {
                "name": "orchestration.daily",
                "display_name": "Daily orchestration",
                "description": "Daily ingest orchestration",
                "parameters": {"ingest_profile": "episodic", "notify_channel": None},
            }
        ]
    )
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 0
    assert "orchestration.daily (Daily orchestration)" in result.output
    assert "Parameters: ingest_profile, notify_channel" in result.output
    assert client.closed is True


def test_pipeline_list_handles_empty(monkeypatch) -> None:
    client = StubPipelineClient(definitions=[])
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 0
    assert "No pipelines are currently registered" in result.output
    assert client.closed is True


def test_pipeline_list_failure(monkeypatch) -> None:
    error = PipelineClientError("boom", status_code=500)
    client = StubPipelineClient(list_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 1
    assert "Pipeline request failed: boom" in result.output
    assert client.closed is True


def test_pipeline_describe_success(monkeypatch) -> None:
    client = StubPipelineClient(
        definition={
            "name": "orchestration.daily",
            "display_name": "Daily orchestration",
            "description": "Daily ingest orchestration",
            "parameters": {"ingest_profile": "episodic"},
        }
    )
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "describe", "orchestration.daily"])

    assert result.exit_code == 0
    assert "Name: orchestration.daily" in result.output
    assert "Display name: Daily orchestration" in result.output
    assert "Parameters:" in result.output
    assert client.requested_name == "orchestration.daily"
    assert client.closed is True


def test_pipeline_describe_missing(monkeypatch) -> None:
    error = PipelineClientError("Pipeline 'missing' was not found.", status_code=404)
    client = StubPipelineClient(describe_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "describe", "missing"])

    assert result.exit_code == 2
    assert "Pipeline 'missing' was not found." in result.output
    assert client.closed is True


def test_pipeline_run_success(monkeypatch) -> None:
    client = StubPipelineClient(
        run_payload={
            "id": "abc123",
            "pipeline": "orchestration.daily",
            "status": "succeeded",
        }
    )
    _install_stub(monkeypatch, client)

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
    assert client.requested_name == "orchestration.daily"
    assert client.run_parameters == {"ingest_profile": "episodic"}
    assert client.closed is True


def test_pipeline_run_rejects_invalid_parameters(monkeypatch) -> None:
    client = StubPipelineClient(run_payload={"id": "abc", "pipeline": "p", "status": "queued"})
    _install_stub(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "run", "orchestration.daily", "--param", "invalid"],
    )

    assert result.exit_code == 2
    assert "Invalid parameter 'invalid'" in result.output
    assert client.requested_name is None
    assert client.closed is False


def test_pipeline_run_missing_pipeline(monkeypatch) -> None:
    error = PipelineClientError("Pipeline 'missing' was not found.", status_code=404)
    client = StubPipelineClient(run_error=error)
    _install_stub(monkeypatch, client)

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


def test_pipeline_run_failure(monkeypatch) -> None:
    error = PipelineClientError("Service unavailable", status_code=503)
    client = StubPipelineClient(run_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run", "orchestration.daily"])

    assert result.exit_code == 1
    assert "Pipeline request failed: Service unavailable" in result.output
    assert client.closed is True
