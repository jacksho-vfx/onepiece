"""Tests covering listing pipeline runs via the CLI."""

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


def test_pipeline_runs_displays_runs(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        runs=[
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "succeeded",
                "created_at": "2024-01-01T10:00:00+00:00",
                "updated_at": "2024-01-01T10:10:00+00:00",
                "parameters": {"ingest_profile": "episodic"},
                "submitted_by": "suite",
                "roles": ["pipeline:run"],
            }
        ]
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "runs"])

    assert result.exit_code == 0
    assert "run-1" in result.output
    assert "Status: succeeded" in result.output
    assert "Submitted by: suite" in result.output
    assert client.closed is True


def test_pipeline_runs_json(monkeypatch: MonkeyPatch) -> None:
    payload = {
        "runs": [
            {
                "id": "run-1",
                "pipeline": "orchestration.daily",
                "status": "succeeded",
            }
        ],
        "next_cursor": None,
    }
    client = StubPipelineClient(runs_payload=payload)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "runs", "--format", "json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == payload
    assert client.closed is True


def test_pipeline_runs_applies_filters(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(runs=[])
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "runs",
            "--pipeline",
            "orchestration.daily",
            "--status",
            "running",
            "--limit",
            "5",
            "--since",
            "2024-01-01T00:00:00+00:00",
        ],
    )

    assert result.exit_code == 0
    assert client.list_runs_kwargs == {
        "pipeline": "orchestration.daily",
        "status": "running",
        "submitted_by": None,
        "role": None,
        "limit": 5,
        "since": "2024-01-01T00:00:00+00:00",
        "before_id": None,
        "before_created_at": None,
    }
    assert client.closed is True


def test_pipeline_runs_filters_by_submitter_and_role(
    monkeypatch: MonkeyPatch,
) -> None:
    client = StubPipelineClient(runs=[])
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "runs",
            "--submitted-by",
            "suite",
            "--role",
            "pipeline:run",
        ],
    )

    assert result.exit_code == 0
    assert client.list_runs_kwargs == {
        "pipeline": None,
        "status": None,
        "submitted_by": "suite",
        "role": "pipeline:run",
        "limit": None,
        "since": None,
        "before_id": None,
        "before_created_at": None,
    }
    assert client.closed is True


def test_pipeline_runs_failure(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("boom", status_code=500)
    client = StubPipelineClient(runs_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "runs"])

    assert result.exit_code == 1
    assert "Pipeline request failed: boom" in result.output
    assert client.closed is True


def test_pipeline_runs_displays_next_page_hint(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        runs_payload={
            "runs": [
                {
                    "id": "run-1",
                    "pipeline": "orchestration.daily",
                    "status": "succeeded",
                    "created_at": "2024-01-01T10:00:00+00:00",
                    "updated_at": "2024-01-01T10:10:00+00:00",
                }
            ],
            "next_cursor": {
                "before_id": "run-0",
                "before_created_at": "2024-01-01T09:00:00+00:00",
            },
        }
    )
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "runs"])

    assert result.exit_code == 0
    assert "More runs available." in result.output
    assert client.closed is True


def test_pipeline_runs_requires_cursor_pairs() -> None:
    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "runs",
            "--before-id",
            "run-123",
        ],
    )

    assert result.exit_code != 0
    terms = ["root", "pipeline", "runs", "[OPTIONS]"]
    for term in terms:
        assert term in result.output


def test_pipeline_runs_requires_limit_with_cursor() -> None:
    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "runs",
            "--before-id",
            "run-123",
            "--before-created-at",
            "2024-01-01T00:00:00+00:00",
        ],
    )

    assert result.exit_code != 0
    terms = ["root", "pipeline", "runs", "[OPTIONS]"]
    for term in terms:
        assert term in result.output
