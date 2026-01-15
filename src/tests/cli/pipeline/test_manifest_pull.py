"""Tests covering manifest pull/push/update/delete commands."""

from __future__ import annotations

from pathlib import Path

try:  # pragma: no cover - python >=3.11 ships tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older versions
    import tomli as tomllib  # type: ignore[no-redef]

import yaml  # type: ignore[import-untyped]
from pytest import MonkeyPatch

from apps.onepiece.app import app as onepiece_app
from apps.onepiece.pipeline.clients import PipelineClientError
from tests.cli.pipeline.conftest import (
    StubPipelineClient,
    install_stub_pipeline_client,
    runner,
    write_pipeline_manifest,
)


def test_pipeline_pull_writes_toml_manifest(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    definition = {
        "name": "orchestration.daily",
        "display_name": "Daily orchestration",
        "description": "Daily ingest orchestration",
        "metadata": {"team": "pipeline"},
        "parameters": {"ingest_profile": {"default": "episodic", "required": False}},
        "steps": [
            {
                "name": "prepare",
                "provider": "tests.pipeline:prepare",
                "config": {"resolution": "4k"},
                "metadata": {"description": "Prep assets"},
            },
            {
                "name": "notify",
                "provider": "tests.pipeline:notify",
                "trigger": {
                    "kind": "event",
                    "event": "ingest.completed",
                    "filters": {"project": "demo"},
                },
            },
        ],
    }
    client = StubPipelineClient(definition=definition)
    install_stub_pipeline_client(monkeypatch, client)

    output = tmp_path / "pipeline.toml"

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "pull",
            "orchestration.daily",
            "--output",
            str(output),
            "--format",
            "toml",
        ],
    )

    assert result.exit_code == 0
    assert output.exists()
    document = tomllib.loads(output.read_text(encoding="utf-8"))
    assert document["name"] == "orchestration.daily"
    assert document["steps"][0]["id"] == "prepare"
    assert document["steps"][0]["with"]["resolution"] == "4k"
    assert document["triggers"][0]["on"] == "ingest.completed"
    trigger_step = document["triggers"][0]["steps"][0]
    assert trigger_step["id"] == "notify"
    assert trigger_step["uses"] == "tests.pipeline:notify"
    assert client.requested_name == "orchestration.daily"
    assert client.closed is True
    assert "written to TOML" in result.output


def test_pipeline_pull_writes_yaml_manifest(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    definition = {
        "name": "daily.render",
        "steps": [
            {
                "name": "prepare",
                "provider": "tests.pipeline:prepare",
                "config": {"resolution": "4k"},
            }
        ],
    }
    client = StubPipelineClient(definition=definition)
    install_stub_pipeline_client(monkeypatch, client)

    output = tmp_path / "manifest.yaml"

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "pull", "daily.render", "--output", str(output)],
    )

    assert result.exit_code == 0
    assert output.exists()
    document = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert document["name"] == "daily.render"
    assert document["steps"][0]["id"] == "prepare"
    assert document["steps"][0]["uses"] == "tests.pipeline:prepare"
    assert client.requested_name == "daily.render"
    assert client.closed is True


def test_pipeline_pull_reports_missing_pipeline(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Pipeline 'missing' was not found.", status_code=404)
    client = StubPipelineClient(describe_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        ["pipeline", "pull", "missing", "--output", "ignored.toml"],
    )

    assert result.exit_code == 2
    assert "Pipeline 'missing' was not found." in result.output
    assert client.closed is True


def test_pipeline_push_registers_definition(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = write_pipeline_manifest(tmp_path, name="create-demo")
    client = StubPipelineClient(create_response={"name": "create-demo"})
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "push", str(manifest)])

    assert result.exit_code == 0
    assert "Pipeline 'create-demo' created" in result.output
    assert client.create_payload is not None
    assert client.create_payload["name"] == "create-demo"
    assert client.closed is True


def test_pipeline_push_reports_conflict(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = write_pipeline_manifest(tmp_path)
    error = PipelineClientError("already exists", status_code=409)
    client = StubPipelineClient(create_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "push", str(manifest)])

    assert result.exit_code == 1
    assert "Pipeline request failed: already exists" in result.output
    assert client.closed is True


def test_pipeline_push_invalid_submission(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = write_pipeline_manifest(tmp_path)
    error = PipelineClientError("bad manifest", status_code=400)
    client = StubPipelineClient(create_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "push", str(manifest)])

    assert result.exit_code == 2
    assert "bad manifest" in result.output
    assert client.closed is True


def test_pipeline_update_replaces_definition(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = write_pipeline_manifest(tmp_path, name="update-demo")
    client = StubPipelineClient(update_response={"name": "update-demo"})
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "update", str(manifest)])

    assert result.exit_code == 0
    assert "Pipeline 'update-demo' updated" in result.output
    assert client.update_name == "update-demo"
    assert client.update_payload is not None
    assert client.update_payload["name"] == "update-demo"
    assert client.closed is True


def test_pipeline_update_invalid_submission(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = write_pipeline_manifest(tmp_path)
    error = PipelineClientError("name mismatch", status_code=400)
    client = StubPipelineClient(update_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "update", str(manifest)])

    assert result.exit_code == 2
    assert "name mismatch" in result.output
    assert client.closed is True


def test_pipeline_delete_removes_definition(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient()
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "delete", "obsolete"])

    assert result.exit_code == 0
    assert "Pipeline 'obsolete' deleted" in result.output
    assert client.delete_name == "obsolete"
    assert client.closed is True


def test_pipeline_delete_missing_definition(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Unknown pipeline", status_code=404)
    client = StubPipelineClient(delete_error=error)
    install_stub_pipeline_client(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "delete", "missing"])

    assert result.exit_code == 2
    assert "Unknown pipeline" in result.output
    assert client.delete_name == "missing"
    assert client.closed is True
