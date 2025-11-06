"""Shared fixtures and helpers for pipeline CLI tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from pytest import MonkeyPatch
from typer.testing import CliRunner

from apps.onepiece.pipeline.clients import PipelineClientError


runner = CliRunner()


@dataclass
class StubPipelineClient:
    """Simple stub implementing the pipeline client protocol for tests."""

    definitions: list[Mapping[str, Any]] | None = None
    definition: Mapping[str, Any] | None = None
    run_payload: Mapping[str, Any] | None = None
    rerun_payload: Mapping[str, Any] | None = None
    runs: list[Mapping[str, Any]] | None = None
    runs_payload: Mapping[str, Any] | None = None
    run_metadata: Mapping[str, Any] | None = None
    run_events: list[Mapping[str, Any]] | None = None
    run_events_history: list[Mapping[str, Any]] | None = None
    list_error: PipelineClientError | None = None
    describe_error: PipelineClientError | None = None
    run_error: PipelineClientError | None = None
    rerun_error: PipelineClientError | None = None
    runs_error: PipelineClientError | None = None
    run_status_error: PipelineClientError | None = None
    run_events_error: PipelineClientError | None = None
    watch_error: PipelineClientError | None = None
    stats_payload: Mapping[str, Any] | None = None
    stats_error: PipelineClientError | None = None
    worker_metrics_payload: Mapping[str, Any] | None = None
    worker_metrics_error: PipelineClientError | None = None
    create_response: Mapping[str, Any] | None = None
    update_response: Mapping[str, Any] | None = None
    create_error: PipelineClientError | None = None
    update_error: PipelineClientError | None = None
    delete_error: PipelineClientError | None = None
    prune_result: Mapping[str, Any] | None = None
    prune_error: PipelineClientError | None = None
    enable_error: PipelineClientError | None = None
    enabled_response: Mapping[str, Any] | None = None

    closed: bool = False
    requested_name: str | None = None
    run_parameters: Mapping[str, Any] | None = None
    rerun_parameters: Mapping[str, Any] | None = None
    rerun_run_id: str | None = None
    list_runs_kwargs: Mapping[str, Any] | None = None
    requested_run_id: str | None = None
    stats_kwargs: Mapping[str, Any] | None = None
    create_payload: Mapping[str, Any] | None = None
    update_payload: Mapping[str, Any] | None = None
    update_name: str | None = None
    delete_name: str | None = None
    worker_metrics_requested: bool = False
    prune_kwargs: Mapping[str, Any] | None = None
    stream_requested: bool = False
    enabled_name: str | None = None
    enabled_state: bool | None = None

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

    def rerun(
        self, run_id: str, overrides: Mapping[str, Any] | None = None
    ) -> Mapping[str, Any]:
        self.rerun_run_id = run_id
        self.rerun_parameters = dict(overrides or {})
        if self.rerun_error:
            raise self.rerun_error
        if self.rerun_payload is None:
            raise AssertionError("rerun payload was not configured")
        return dict(self.rerun_payload)

    def list_runs(
        self,
        *,
        pipeline: str | None = None,
        status: str | None = None,
        submitted_by: str | None = None,
        role: str | None = None,
        limit: int | None = None,
        since: str | None = None,
        before_id: str | None = None,
        before_created_at: str | None = None,
    ) -> Mapping[str, Any]:
        self.list_runs_kwargs = {
            "pipeline": pipeline,
            "status": status,
            "submitted_by": submitted_by,
            "role": role,
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

    def get_run_events(self, run_id: str) -> list[Mapping[str, Any]]:
        self.requested_run_id = run_id
        if self.run_events_error:
            raise self.run_events_error
        if self.run_events_history is None:
            raise AssertionError("run events history was not configured")
        return [dict(event) for event in self.run_events_history]

    def stream_events(self, run_id: str) -> Iterable[Mapping[str, Any]]:
        self.requested_run_id = run_id
        self.stream_requested = True
        if self.watch_error:
            raise self.watch_error
        for event in self.run_events or []:
            yield dict(event)

    def get_stats(
        self,
        *,
        since: str | None = None,
        include_durations: bool = False,
        pipeline: str | None = None,
    ) -> Mapping[str, Any]:
        self.stats_kwargs = {
            "since": since,
            "include_durations": include_durations,
            "pipeline": pipeline,
        }
        if self.stats_error:
            raise self.stats_error
        if self.stats_payload is None:
            raise AssertionError("stats payload was not configured")
        return dict(self.stats_payload)

    def worker_pool_metrics(self) -> Mapping[str, Any]:
        self.worker_metrics_requested = True
        if self.worker_metrics_error:
            raise self.worker_metrics_error
        if self.worker_metrics_payload is None:
            raise AssertionError("worker metrics payload was not configured")
        return dict(self.worker_metrics_payload)

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

    def prune_runs(
        self,
        *,
        max_age_hours: float | None = None,
        max_runs: int | None = None,
    ) -> Mapping[str, Any]:
        self.prune_kwargs = {
            "max_age_hours": max_age_hours,
            "max_runs": max_runs,
        }
        if self.prune_error:
            raise self.prune_error
        if self.prune_result is None:
            raise AssertionError("prune result was not configured")
        return dict(self.prune_result)

    def set_definition_enabled(self, name: str, enabled: bool) -> Mapping[str, Any]:
        self.enabled_name = name
        self.enabled_state = enabled
        if self.enable_error:
            raise self.enable_error
        if self.enabled_response is None:
            raise AssertionError("enabled response was not configured")
        return dict(self.enabled_response)

    def close(self) -> None:
        self.closed = True


def install_stub_pipeline_client(
    monkeypatch: MonkeyPatch, client: StubPipelineClient
) -> StubPipelineClient:
    """Install the provided stub client into the pipeline module."""
    from apps.onepiece import pipeline as pipeline_module

    monkeypatch.setattr(pipeline_module, "_create_pipeline_client", lambda: client)
    return client


def write_pipeline_manifest(tmp_path: Path, name: str = "demo") -> Path:
    """Write a minimal pipeline manifest to the provided path."""
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


__all__ = [
    "StubPipelineClient",
    "install_stub_pipeline_client",
    "runner",
    "write_pipeline_manifest",
]
