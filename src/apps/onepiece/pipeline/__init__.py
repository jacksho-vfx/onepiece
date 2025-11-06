"""Typer application for interacting with the pipeline orchestrator."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Mapping

import typer

from .clients import (
    LocalPipelineClient,
    PipelineClient,
    PipelineClientError,
    RemotePipelineClient,
    create_pipeline_client,
)
from .io import (
    _load_pipeline_parameters_file,
    _load_pipeline_submission,
    _parse_pipeline_parameters,
    _resolve_manifest_format,
    _serialised_definition_to_manifest,
    _write_manifest,
)
from .output import (
    _coerce_display_text,
    _format_pipeline_definition,
    _format_pipeline_prune_summary,
    _format_pipeline_run,
    _format_pipeline_statistics,
    _format_run_event,
    _format_worker_metrics,
    _normalise_roles,
    _render_pipeline_details,
)


def _create_pipeline_client() -> PipelineClient:
    return create_pipeline_client()


app = typer.Typer(
    name="pipeline",
    help="Interact with the OnePiece pipeline orchestrator.",
)


def _using_client() -> AbstractContextManager[PipelineClient]:
    class _Context(AbstractContextManager[PipelineClient]):
        def __init__(self) -> None:
            self._client = _create_pipeline_client()

        def __enter__(self) -> PipelineClient:
            return self._client

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            self._client.close()
            return None

    return _Context()


_VALID_OUTPUT_FORMATS = {"text", "json"}


def _resolve_output_format(raw: str) -> str:
    value = raw.strip().lower()
    if not value:
        return "text"
    if value not in _VALID_OUTPUT_FORMATS:
        raise typer.BadParameter(
            "--format must be either 'text' or 'json'.",
            param_hint="--format",
        )
    return value


@app.command("list")
def list_pipelines(
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """List pipelines exposed by the orchestrator."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            definitions = client.list_definitions()
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(definitions, indent=2))
        return

    if not definitions:
        typer.echo("No pipelines are currently registered with the orchestrator.")
        raise typer.Exit(code=0)

    for definition in definitions:
        for line in _format_pipeline_definition(definition):
            typer.echo(line)


@app.command("describe")
def describe_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Describe a specific pipeline."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            definition = client.get_definition(name)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(definition, indent=2))
        return

    _render_pipeline_details(definition)


def _toggle_pipeline_state(name: str, *, enabled: bool, output_format: str) -> None:
    with _using_client() as client:
        try:
            definition = client.set_definition_enabled(name, enabled)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(definition, indent=2))
        return

    state = "enabled" if enabled else "disabled"
    pipeline_name = definition.get("name") or name
    typer.echo(f"Pipeline '{pipeline_name}' {state}.")


@app.command("enable")
def enable_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Enable a pipeline definition."""

    output_format = _resolve_output_format(format)
    _toggle_pipeline_state(name, enabled=True, output_format=output_format)


@app.command("disable")
def disable_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Disable a pipeline definition."""

    output_format = _resolve_output_format(format)
    _toggle_pipeline_state(name, enabled=False, output_format=output_format)


@app.command("pull")
def pull_pipeline_definition(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Destination manifest file (TOML or YAML).",
    ),
    manifest_format: str | None = typer.Option(
        None,
        "--format",
        "-f",
        help="Output format ('toml' or 'yaml'). Defaults to the --output suffix.",
    ),
) -> None:
    """Fetch a pipeline definition and write it to a manifest file."""

    with _using_client() as client:
        try:
            definition = client.get_definition(name)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    manifest = _serialised_definition_to_manifest(definition)
    selected_format = _resolve_manifest_format(output, manifest_format)

    try:
        _write_manifest(output, manifest, format=selected_format)
    except OSError as exc:  # pragma: no cover - depends on filesystem errors
        typer.echo(f"Failed to write manifest: {exc}")
        raise typer.Exit(code=1) from exc

    pipeline_name = manifest.get("name") or name
    typer.echo(
        "Pipeline '{pipeline}' written to {fmt} manifest at {path}.".format(
            pipeline=pipeline_name,
            fmt=selected_format.upper(),
            path=output,
        )
    )


@app.command("push")
def push_pipeline_definition(
    manifest: Path = typer.Argument(..., help="TOML or YAML pipeline manifest."),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Pipeline name when the manifest contains multiple entries.",
    ),
) -> None:
    """Register a new pipeline definition from a manifest file."""

    submission = _load_pipeline_submission(manifest, name=name)

    with _using_client() as client:
        try:
            result = client.create_definition(submission)
        except PipelineClientError as exc:
            if exc.status_code == 400:
                raise typer.BadParameter(exc.message, param_hint="manifest") from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            if exc.status_code == 409:
                raise typer.Exit(code=1) from exc
            raise typer.Exit(code=1) from exc

    pipeline_name = str(result.get("name", submission["name"]))
    typer.echo(
        f"Pipeline '{pipeline_name}' created from {manifest.resolve()}.",
    )


@app.command("update")
def update_pipeline_definition(
    manifest: Path = typer.Argument(..., help="TOML or YAML pipeline manifest."),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Pipeline name when the manifest contains multiple entries.",
    ),
) -> None:
    """Replace an existing pipeline definition from a manifest file."""

    submission = _load_pipeline_submission(manifest, name=name)
    pipeline_name = str(submission["name"])

    with _using_client() as client:
        try:
            result = client.update_definition(pipeline_name, submission)
        except PipelineClientError as exc:
            if exc.status_code == 400:
                raise typer.BadParameter(exc.message, param_hint="manifest") from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    resolved_name = str(result.get("name", pipeline_name))
    typer.echo(
        f"Pipeline '{resolved_name}' updated from {manifest.resolve()}.",
    )


@app.command("delete")
def delete_pipeline_definition(
    name: str = typer.Argument(..., help="Pipeline identifier to remove."),
) -> None:
    """Delete a pipeline definition from the orchestrator."""

    with _using_client() as client:
        try:
            client.delete_definition(name)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message, param_hint="name") from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    typer.echo(f"Pipeline '{name}' deleted from the orchestrator.")


@app.command("run")
def run_pipeline(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    *,
    params_file: Path | None = typer.Option(
        None,
        "--params-file",
        help="Path to a JSON or TOML document with pipeline parameters.",
    ),
    parameters: list[str] | None = typer.Option(
        None,
        "--param",
        "-p",
        help="Key=value parameters forwarded to the orchestrator.",
    ),
    wait: bool = typer.Option(
        False,
        "--wait/--no-wait",
        help="Follow run events until the pipeline finishes.",
    ),
    format: str = typer.Option(
        "text",
        "--format",
        help="Output format: 'text' (default) or 'json'.",
    ),
) -> None:
    """Trigger a pipeline execution."""

    output_format = _resolve_output_format(format)

    if wait and output_format == "json":
        raise typer.BadParameter(
            "--wait cannot be combined with '--format json'.",
            param_hint="--wait",
        )

    file_parameters: Mapping[str, Any] | None = None
    if params_file is not None:
        try:
            file_parameters = _load_pipeline_parameters_file(params_file)
        except PipelineClientError as exc:
            raise typer.BadParameter(exc.message, param_hint="--params-file") from exc

    try:
        parsed_parameters = _parse_pipeline_parameters(parameters, base=file_parameters)
    except PipelineClientError as exc:
        raise typer.BadParameter(exc.message) from exc

    with _using_client() as client:
        try:
            run = client.trigger_run(name, parsed_parameters)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

        pipeline_name = run.get("pipeline", name)
        raw_run_id = run.get("id")
        run_id = str(raw_run_id) if raw_run_id is not None else "<unknown>"
        status = run.get("status", "unknown")

        if output_format == "json":
            typer.echo(json.dumps(run, indent=2))
            return

        typer.echo(f"Triggered pipeline '{pipeline_name}' (run id: {run_id}).")
        typer.echo(f"Current status: {status}")
        initiator = _coerce_display_text(run.get("submitted_by"))
        if initiator:
            typer.echo(f"Initiated by: {initiator}")
            role_list = _normalise_roles(run.get("roles"))
            if role_list:
                typer.echo("Roles: " + ", ".join(role_list))

        if wait:
            if raw_run_id is None:
                typer.echo(
                    "Cannot wait for completion: run identifier was not provided."
                )
                return

            typer.echo("Waiting for run to complete...")
            final_status: str | None = None
            try:
                for event in client.stream_events(str(raw_run_id)):
                    for line in _format_run_event(event):
                        typer.echo(line)
                    event_status = str(event.get("status", "")).lower()
                    if event_status in {"succeeded", "failed"}:
                        final_status = str(event.get("status", ""))
                        break
            except PipelineClientError as exc:
                if exc.status_code == 404:
                    raise typer.BadParameter(exc.message) from exc
                typer.echo(f"Pipeline request failed: {exc.message}")
                raise typer.Exit(code=1) from exc

            if final_status is not None:
                typer.echo(f"Run completed with status: {final_status}")


@app.command("runs")
def list_runs(
    pipeline: str | None = typer.Option(
        None,
        "--pipeline",
        "-p",
        help="Filter runs for a specific pipeline.",
    ),
    status: str | None = typer.Option(
        None,
        "--status",
        help="Filter runs by status.",
    ),
    submitted_by: str | None = typer.Option(
        None,
        "--submitted-by",
        help="Filter runs by the submitting principal.",
    ),
    role: str | None = typer.Option(
        None,
        "--role",
        help="Filter runs that include the specified submitting role.",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Maximum number of runs to display.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Return runs created on or after the ISO timestamp.",
    ),
    before_id: str | None = typer.Option(
        None,
        "--before-id",
        help="Return runs created before the provided run id.",
    ),
    before_created_at: str | None = typer.Option(
        None,
        "--before-created-at",
        help="Return runs created before the provided ISO timestamp.",
    ),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """List pipeline runs recorded by the orchestrator."""

    output_format = _resolve_output_format(format)

    if (before_id is None) ^ (before_created_at is None):
        raise typer.BadParameter(
            "Both --before-id and --before-created-at must be provided together."
        )
    if before_id is not None and limit is None:
        raise typer.BadParameter(
            "--limit must be provided when using pagination cursors."
        )
    if role is not None and not role.strip():
        raise typer.BadParameter("--role must be a non-empty value.")
    if submitted_by is not None and not submitted_by.strip():
        raise typer.BadParameter("--submitted-by must be a non-empty value.")

    with _using_client() as client:
        try:
            page = client.list_runs(
                pipeline=pipeline,
                status=status,
                submitted_by=submitted_by,
                role=role,
                limit=limit,
                since=since,
                before_id=before_id,
                before_created_at=before_created_at,
            )
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(page, indent=2))
        return

    runs_payload = page.get("runs") if isinstance(page, Mapping) else None
    runs_list = runs_payload if isinstance(runs_payload, list) else []

    if not runs_list:
        typer.echo("No pipeline runs were found.")
        raise typer.Exit(code=0)

    for run in runs_list:
        for line in _format_pipeline_run(run):
            typer.echo(line)

    cursor_payload = page.get("next_cursor") if isinstance(page, Mapping) else None
    if isinstance(cursor_payload, Mapping):
        cursor_before_id = cursor_payload.get("before_id")
        cursor_before_created_at = cursor_payload.get("before_created_at")
        if cursor_before_id and cursor_before_created_at:
            typer.echo(
                "More runs available. Re-run with --before-id"
                f" {cursor_before_id} --before-created-at {cursor_before_created_at}."
            )


@app.command("stats")
def show_statistics(
    include_durations: bool = typer.Option(
        False,
        "--include-durations",
        "-d",
        help="Display duration summaries for each status grouping.",
    ),
    pipeline: str | None = typer.Option(
        None,
        "--pipeline",
        help="Restrict statistics to the specified pipeline.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Restrict statistics to runs created on or after the ISO timestamp.",
    ),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display aggregated pipeline run statistics."""

    output_format = _resolve_output_format(format)

    pipeline_filter: str | None = None
    if pipeline is not None:
        pipeline_filter = pipeline.strip()
        if not pipeline_filter:
            raise typer.BadParameter("Pipeline name must not be blank.")

    with _using_client() as client:
        try:
            stats = client.get_stats(
                since=since,
                include_durations=include_durations,
                pipeline=pipeline_filter,
            )
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(stats, indent=2))
        return

    pipelines = stats.get("pipelines")
    if not isinstance(pipelines, Mapping) or not pipelines:
        typer.echo("No pipeline run statistics available.")
        raise typer.Exit(code=0)

    for line in _format_pipeline_statistics(stats):
        typer.echo(line)


@app.command("workers")
def show_worker_metrics(
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display current worker pool utilisation."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            metrics = client.worker_pool_metrics()
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(metrics, indent=2))
        return

    typer.echo(_format_worker_metrics(metrics))


@app.command("prune")
def prune_history(
    max_age_hours: float | None = typer.Option(
        None,
        "--max-age-hours",
        help="Prune runs created before the provided number of hours ago.",
        min=0.0,
    ),
    max_runs: int | None = typer.Option(
        None,
        "--max-runs",
        help="Retain at most this many recent runs when pruning.",
        min=0,
    ),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Apply pipeline run retention policies and report the outcome."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            result = client.prune_runs(
                max_age_hours=max_age_hours,
                max_runs=max_runs,
            )
        except PipelineClientError as exc:
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(result, indent=2))
        return

    for line in _format_pipeline_prune_summary(result):
        typer.echo(line)


@app.command("run-status")
def run_status(
    run_id: str = typer.Argument(..., help="Run identifier."),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display metadata for a specific pipeline run."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            run = client.get_run(run_id)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(run, indent=2))
        return

    for line in _format_pipeline_run(run):
        typer.echo(line)


@app.command("run-events")
def run_events(
    run_id: str = typer.Argument(..., help="Run identifier."),
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display recorded events for a pipeline run."""

    output_format = _resolve_output_format(format)

    with _using_client() as client:
        try:
            events = client.get_run_events(run_id)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(events, indent=2))
        return

    if not events:
        typer.echo(f"No events recorded for run '{run_id}'.")
        return

    for event in events:
        for line in _format_run_event(event):
            typer.echo(line)


@app.command("watch")
def watch_run(
    run_id: str = typer.Argument(..., help="Run identifier."),
) -> None:
    """Stream live status events for a pipeline run."""

    with _using_client() as client:
        try:
            events = client.stream_events(run_id)
            for event in events:
                for line in _format_run_event(event):
                    typer.echo(line)
        except PipelineClientError as exc:
            if exc.status_code == 404:
                raise typer.BadParameter(exc.message) from exc
            typer.echo(f"Pipeline request failed: {exc.message}")
            raise typer.Exit(code=1) from exc


__all__ = [
    "app",
    "create_pipeline_client",
    "LocalPipelineClient",
    "RemotePipelineClient",
    "PipelineClient",
    "PipelineClientError",
]
