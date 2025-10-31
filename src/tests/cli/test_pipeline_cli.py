"""Tests for the OnePiece pipeline CLI surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from pytest import MonkeyPatch
from typing import Any, Iterable, Mapping

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
    runs: list[Mapping[str, Any]] | None = None
    runs_payload: Mapping[str, Any] | None = None
    run_metadata: Mapping[str, Any] | None = None
    run_events: list[Mapping[str, Any]] | None = None
    list_error: PipelineClientError | None = None
    describe_error: PipelineClientError | None = None
    run_error: PipelineClientError | None = None
    runs_error: PipelineClientError | None = None
    run_status_error: PipelineClientError | None = None
    watch_error: PipelineClientError | None = None
    stats_payload: Mapping[str, Any] | None = None
    stats_error: PipelineClientError | None = None
    create_response: Mapping[str, Any] | None = None
    update_response: Mapping[str, Any] | None = None
    create_error: PipelineClientError | None = None
    update_error: PipelineClientError | None = None
    delete_error: PipelineClientError | None = None

    closed: bool = False
    requested_name: str | None = None
    run_parameters: Mapping[str, Any] | None = None
    list_runs_kwargs: Mapping[str, Any] | None = None
    requested_run_id: str | None = None
    stats_kwargs: Mapping[str, Any] | None = None
    create_payload: Mapping[str, Any] | None = None
    update_payload: Mapping[str, Any] | None = None
    update_name: str | None = None
    delete_name: str | None = None

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

    def trigger_run(
        self, name: str, parameters: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.requested_name = name
        self.run_parameters = dict(parameters)
        if self.run_error:
            raise self.run_error
        if self.run_payload is None:
            raise AssertionError("run payload was not configured")
        return dict(self.run_payload)

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        limit: int | None = None,
        since: str | None = None,
        before_id: str | None = None,
        before_created_at: str | None = None,
    ) -> Mapping[str, Any]:
        self.list_runs_kwargs = {
            "pipeline": pipeline,
            "status": status,
            "limit": limit,
            "since": since,
            "before_id": before_id,
            "before_created_at": before_created_at,
        }
        if self.runs_error:
            raise self.runs_error
        if self.runs_payload is not None:
            return dict(self.runs_payload)
        return {"runs": list(self.runs or []), "next_cursor": None}

    def get_run(self, run_id: str) -> Mapping[str, Any]:
        self.requested_run_id = run_id
        if self.run_status_error:
            raise self.run_status_error
        if self.run_metadata is None:
            raise AssertionError("run metadata was not configured")
        return dict(self.run_metadata)

    def stream_events(self, run_id: str) -> Iterable[Mapping[str, Any]]:
        self.requested_run_id = run_id
        if self.watch_error:
            raise self.watch_error
        for event in self.run_events or []:
            yield dict(event)

    def get_stats(
        self,
        *,
        since: str | None = None,
        include_durations: bool = False,
    ) -> Mapping[str, Any]:
        self.stats_kwargs = {
            "since": since,
            "include_durations": include_durations,
        }
        if self.stats_error:
            raise self.stats_error
        if self.stats_payload is None:
            raise AssertionError("stats payload was not configured")
        return dict(self.stats_payload)

    def create_definition(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.create_payload = dict(payload)
        if self.create_error:
            raise self.create_error
        if self.create_response is None:
            raise AssertionError("create response was not configured")
        return dict(self.create_response)

    def update_definition(
        self, name: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.update_name = name
        self.update_payload = dict(payload)
        if self.update_error:
            raise self.update_error
        if self.update_response is None:
            raise AssertionError("update response was not configured")
        return dict(self.update_response)

    def delete_definition(self, name: str) -> None:
        self.delete_name = name
        if self.delete_error:
            raise self.delete_error

    def close(self) -> None:
        self.closed = True


def _install_stub(
    monkeypatch: MonkeyPatch, client: StubPipelineClient
) -> StubPipelineClient:
    from apps.onepiece import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "_create_pipeline_client", lambda: client)
    return client


def _write_pipeline_manifest(tmp_path: Path, name: str = "demo") -> Path:
    manifest = tmp_path / "pipeline.toml"
    manifest.write_text(
        "\n".join(
            [
                f'name = "{name}"',
                "",
                "[[steps]]",
                'id = "prepare"',
                'uses = "tests.pipeline:prepare"',
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def test_pipeline_command_group_loads() -> None:
    result = runner.invoke(onepiece_app, ["pipeline", "--help"])

    assert result.exit_code == 0
    assert "Interact with the OnePiece pipeline orchestrator." in result.output
    assert "list" in result.output
    assert "describe" in result.output
    assert "run" in result.output
    assert "runs" in result.output
    assert "stats" in result.output
    assert "run-status" in result.output
    assert "watch" in result.output
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
    _install_stub(monkeypatch, client)

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
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 0
    assert "No pipelines are currently registered" in result.output
    assert client.closed is True


def test_pipeline_list_failure(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("boom", status_code=500)
    client = StubPipelineClient(list_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "list"])

    assert result.exit_code == 1
    assert "Pipeline request failed: boom" in result.output
    assert client.closed is True


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
    _install_stub(monkeypatch, client)

    result = runner.invoke(
        onepiece_app, ["pipeline", "describe", "orchestration.daily"]
    )

    assert result.exit_code == 0
    assert "Name: orchestration.daily" in result.output
    assert "Display name: Daily orchestration" in result.output
    assert "Parameters:" in result.output
    assert "  - ingest_profile (default=episodic)" in result.output
    assert "Profile to use" in result.output
    assert client.requested_name == "orchestration.daily"
    assert client.closed is True


def test_pipeline_describe_missing(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Pipeline 'missing' was not found.", status_code=404)
    client = StubPipelineClient(describe_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "describe", "missing"])

    assert result.exit_code == 2
    assert "Pipeline 'missing' was not found." in result.output
    assert client.closed is True


def test_pipeline_push_registers_definition(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _write_pipeline_manifest(tmp_path, name="create-demo")
    client = StubPipelineClient(create_response={"name": "create-demo"})
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "push", str(manifest)])

    assert result.exit_code == 0
    assert "Pipeline 'create-demo' created" in result.output
    assert client.create_payload is not None
    assert client.create_payload["name"] == "create-demo"
    assert client.closed is True


def test_pipeline_push_reports_conflict(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _write_pipeline_manifest(tmp_path)
    error = PipelineClientError("already exists", status_code=409)
    client = StubPipelineClient(create_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "push", str(manifest)])

    assert result.exit_code == 1
    assert "Pipeline request failed: already exists" in result.output
    assert client.closed is True


def test_pipeline_push_invalid_submission(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _write_pipeline_manifest(tmp_path)
    error = PipelineClientError("bad manifest", status_code=400)
    client = StubPipelineClient(create_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "push", str(manifest)])

    assert result.exit_code == 2
    assert "bad manifest" in result.output
    assert client.closed is True


def test_pipeline_update_replaces_definition(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest = _write_pipeline_manifest(tmp_path, name="update-demo")
    client = StubPipelineClient(update_response={"name": "update-demo"})
    _install_stub(monkeypatch, client)

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
    manifest = _write_pipeline_manifest(tmp_path)
    error = PipelineClientError("name mismatch", status_code=400)
    client = StubPipelineClient(update_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "update", str(manifest)])

    assert result.exit_code == 2
    assert "name mismatch" in result.output
    assert client.closed is True


def test_pipeline_delete_removes_definition(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient()
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "delete", "obsolete"])

    assert result.exit_code == 0
    assert "Pipeline 'obsolete' deleted" in result.output
    assert client.delete_name == "obsolete"
    assert client.closed is True


def test_pipeline_delete_missing_definition(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Unknown pipeline", status_code=404)
    client = StubPipelineClient(delete_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "delete", "missing"])

    assert result.exit_code == 2
    assert "Unknown pipeline" in result.output
    assert client.delete_name == "missing"
    assert client.closed is True


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
    assert "Initiated by: suite" in result.output
    assert "Roles: pipeline:manage, pipeline:run" in result.output
    assert client.requested_name == "orchestration.daily"
    assert client.run_parameters == {"ingest_profile": "episodic"}
    assert client.closed is True


def test_pipeline_run_rejects_invalid_parameters(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        run_payload={"id": "abc", "pipeline": "p", "status": "queued"}
    )
    _install_stub(monkeypatch, client)

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


def test_pipeline_run_failure(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Service unavailable", status_code=503)
    client = StubPipelineClient(run_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run", "orchestration.daily"])

    assert result.exit_code == 1
    assert "Pipeline request failed: Service unavailable" in result.output
    assert client.closed is True


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
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "runs"])

    assert result.exit_code == 0
    assert "Run run-1" in result.output
    assert "Pipeline: orchestration.daily" in result.output
    assert "Parameters:" in result.output
    assert "Submitted by: suite" in result.output
    assert client.closed is True


def test_pipeline_runs_applies_filters(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(runs=[])
    _install_stub(monkeypatch, client)

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
        "limit": 5,
        "since": "2024-01-01T00:00:00+00:00",
        "before_id": None,
        "before_created_at": None,
    }
    assert client.closed is True


def test_pipeline_runs_failure(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("boom", status_code=500)
    client = StubPipelineClient(runs_error=error)
    _install_stub(monkeypatch, client)

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
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "runs"])

    assert result.exit_code == 0
    assert "More runs available." in result.output


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
    terms = ["Both", "--before-id", "--before-created-at"]
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
    assert "--limit must be provided" in result.output


def test_pipeline_stats_displays_results(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(
        stats_payload={
            "pipelines": {
                "render": {
                    "succeeded": {
                        "count": 2,
                        "durations": {
                            "average_seconds": 12.5,
                            "min_seconds": 10.0,
                            "max_seconds": 15.0,
                        },
                    },
                    "failed": {"count": 1},
                }
            }
        }
    )
    _install_stub(monkeypatch, client)

    result = runner.invoke(
        onepiece_app,
        [
            "pipeline",
            "stats",
            "--include-durations",
            "--since",
            "2024-01-01T00:00:00+00:00",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "Pipeline: render" in result.output
    assert "succeeded: 2 runs (avg 12.50s" in result.output
    assert client.stats_kwargs == {
        "since": "2024-01-01T00:00:00+00:00",
        "include_durations": True,
    }
    assert client.closed is True


def test_pipeline_stats_handles_empty(monkeypatch: MonkeyPatch) -> None:
    client = StubPipelineClient(stats_payload={"pipelines": {}})
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "stats"])

    assert result.exit_code == 0
    assert "No pipeline run statistics available." in result.output
    assert client.closed is True


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
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run-status", "run-1"])

    assert result.exit_code == 0
    assert "Run run-1" in result.output
    assert "Status: running" in result.output
    assert "Submitted by: suite" in result.output
    assert client.requested_run_id == "run-1"
    assert client.closed is True


def test_pipeline_run_status_missing(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Run not found", status_code=404)
    client = StubPipelineClient(run_status_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "run-status", "run-1"])

    assert result.exit_code == 2
    assert "Run not found" in result.output
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
    _install_stub(monkeypatch, client)

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
    _install_stub(monkeypatch, client)

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
                "parameters": {"error": "step ingest failed"},
            }
        ]
    )
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "watch", "run-1"])

    assert result.exit_code == 0
    assert "failed" in result.output
    assert "Error: step ingest failed" in result.output


def test_pipeline_watch_missing_run(monkeypatch: MonkeyPatch) -> None:
    error = PipelineClientError("Run not found", status_code=404)
    client = StubPipelineClient(watch_error=error)
    _install_stub(monkeypatch, client)

    result = runner.invoke(onepiece_app, ["pipeline", "watch", "run-1"])

    assert result.exit_code == 2
    assert "Run not found" in result.output
    assert client.closed is True
