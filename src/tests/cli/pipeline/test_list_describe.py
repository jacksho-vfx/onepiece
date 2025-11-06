"""Tests covering list and describe commands for pipeline CLI."""

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


def test_pipeline_command_group_loads() -> None:
    result = runner.invoke(onepiece_app, ["pipeline", "--help"])

    assert result.exit_code == 0
    assert "Interact with the OnePiece pipeline orchestrator." in result.output
    assert "list" in result.output
    assert "describe" in result.output
    assert "run" in result.output
    assert "runs" in result.output
    assert "run-events" in result.output
    assert "stats" in result.output
    # assert "workers" in result.output
    assert "run-status" in result.output
    assert "watch" in result.output
    assert "pull" in result.output
    assert "push" in result.output
    assert "update" in result.output
    assert "delete" in result.output


def test_pipeline_list_displays_definitions(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        definitions=[
            {
                "name": "orchestration.daily",
                "display_name": "Daily orchestration",
                "description": "Daily ingest orchestration",
                "parameters": {
                    "ingest_profile": {"default": "episodic"},
                    "notify_channel": {"required": True},
                },
            }
        ]
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 0
    assert "orchestration.daily (Daily orchestration)" in result.output
    assert (
        "Parameters: ingest_profile (default=episodic), notify_channel (required)"
        in result.output
    )
    assert client.closed is True


def test_pipeline_list_handles_empty(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(definitions=[])
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 0
    assert "No pipelines are currently registered" in result.output
    assert client.closed is True


def test_pipeline_list_supports_json(monkeypatch: MonkeyPatch) -> None:
    payload = [
        {
            "name": "orchestration.daily",
            "display_name": "Daily orchestration",
            "description": "Daily ingest orchestration",
        }
    ]
    client = StubPipelineClient(definitions=payload)  # type: ignore[arg-type]
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "list", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.closed is True


def test_pipeline_list_empty_json(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(definitions=[])
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == []
    assert client.closed is True


def test_pipeline_list_failure(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("boom", status_code=500)
    client = StubPipelineClient(list_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 1
    assert "Pipeline request failed: boom" in result.output
    assert client.closed is True


def test_pipeline_list_marks_disabled_pipelines(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        definitions=[
            {
                "name": "orchestration.daily",
                "display_name": "Daily orchestration",
                "enabled": False,
            }
        ]
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 0
    assert "orchestration.daily (Daily orchestration) [disabled]" in result.output


def test_pipeline_describe_success(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        definition={
            "name": "orchestration.daily",
            "display_name": "Daily orchestration",
            "description": "Daily ingest orchestration",
            "parameters": {
                "ingest_profile": {
                    "default": "episodic",
                    "description": "Profile to use",
                }
            },
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app, ["pipeline", "describe", "orchestration.daily"]
    )

    assert result.exit_code == 0
    assert "Name: orchestration.daily" in result.output
    assert "Display name: Daily orchestration" in result.output
    assert "Enabled: yes" in result.output
    assert "Parameters:" in result.output
    assert "  - ingest_profile (default=episodic)" in result.output
    assert "Profile to use" in result.output
    assert client.requested_name == "orchestration.daily"
    assert client.closed is True


def test_pipeline_describe_json(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "name": "orchestration.daily",
        "display_name": "Daily orchestration",
    }
    client = StubPipelineClient(definition=payload)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "describe", "orchestration.daily", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.closed is True


def test_pipeline_describe_missing(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Pipeline 'missing' was not found.", status_code=404)
    client = StubPipelineClient(describe_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "describe", "missing"])

    assert result.exit_code == 2
    assert "Pipeline 'missing' was not found." in result.output
    assert client.closed is True


def test_pipeline_enable_command_updates_state(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(enabled_response={"name": "render", "enabled": True})
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "enable", "render"])

    assert result.exit_code == 0
    assert "Pipeline 'render' enabled." in result.output
    assert client.enabled_name == "render"
    assert client.enabled_state is True
    assert client.closed is True


def test_pipeline_disable_command_updates_state(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(enabled_response={"name": "render", "enabled": False})
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "disable", "render"])

    assert result.exit_code == 0
    assert "Pipeline 'render' disabled." in result.output
    assert client.enabled_state is False
    assert client.closed is True


def test_pipeline_enable_command_supports_json(monkeypatch: MonkeyPatch) -> None:
    payload = {"name": "render", "enabled": True}
    client = StubPipelineClient(enabled_response=payload)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "enable", "render", "--format", "json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.closed is True


def test_pipeline_enable_command_handles_errors(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("not found", status_code=404)
    client = StubPipelineClient(enable_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "enable", "missing"])

    assert result.exit_code == 2
    assert "not found" in result.output
