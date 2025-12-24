"""Typer CLI entry points for the Trafalgar dashboard services."""

from datetime import datetime, timedelta, timezone
from importlib import import_module
from multiprocessing import Process
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

import json
import os
import secrets
import webbrowser

import typer

try:  # pragma: no cover - Python 3.11+ ships tomllib
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older interpreters
    import tomli as tomllib  # type: ignore[no-redef]

from apps.onepiece.config import load_profile
from apps.trafalgar.pipeline import (
    PipelineDefinition,
    configure_orchestrator_from_profile,
    get_pipeline_orchestrator,
    pipeline_definition_from_profile_entry,
    PipelineRun,
    WorkerPoolMetrics,
)
from apps.trafalgar.pipeline_manifest import translate_pipeline_manifest
from apps.trafalgar.providers.providers import (
    ProviderNotFoundError,
    ReconcileDataProvider,
    initialize_providers,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
DEMO_DASHBOARD_TOKEN = "demo-dashboard-token"

app = typer.Typer(
    name="trafalgar",
    help=(
        "Operations for the Trafalgar dashboard. Use `trafalgar auth generate-token` "
        "to create bearer tokens before enabling endpoints guarded by "
        "`require_dashboard_auth`."
    ),
)
web_app = typer.Typer(name="web", help="Web interface helpers.")
ingest_app = typer.Typer(
    name="ingest",
    help="Ingestion helper application.",
    invoke_without_command=True,
)
auth_app = typer.Typer(name="auth", help="Authentication helpers for the dashboard.")
pipeline_app = typer.Typer(
    name="pipeline",
    help="Interact with the Trafalgar pipeline orchestrator.",
)

_VALID_OUTPUT_FORMATS = {"text", "json"}


@pipeline_app.callback()
def _bootstrap_pipeline_orchestrator(_ctx: typer.Context) -> None:
    """Load profile configuration before executing pipeline commands."""

    context = load_profile()
    configure_orchestrator_from_profile(
        context, storage_config=context.pipeline_storage
    )


def _format_pipeline_definition(definition: PipelineDefinition) -> Any:
    display = definition.display_name or definition.name
    if display == definition.name:
        return definition.name
    return f"{definition.name} ({display})"


def _format_pipeline_statistics(
    stats: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> list[str]:
    lines: list[str] = []
    for pipeline in sorted(stats):
        lines.append(f"Pipeline: {pipeline}")
        statuses = stats[pipeline]
        if not statuses:
            lines.append("  No runs recorded.")
            continue
        for status in sorted(statuses):
            entry = statuses[status]
            count = entry.get("count", 0)
            try:
                count_int = int(count)
            except (TypeError, ValueError):
                count_int = 0
            plural = "s" if count_int != 1 else ""
            line = f"  {status}: {count_int} run{plural}"
            details: list[str] = []
            durations = entry.get("durations")
            if isinstance(durations, Mapping):
                average = durations.get("average_seconds")
                minimum = durations.get("min_seconds")
                maximum = durations.get("max_seconds")
                if all(
                    isinstance(value, (int, float))
                    for value in (average, minimum, maximum)
                ):
                    details.append(
                        f"avg {float(average):.2f}s, min {float(minimum):.2f}s, max {float(maximum):.2f}s"  # type: ignore[arg-type]
                    )
            queue_waits = entry.get("queue_waits")
            if isinstance(queue_waits, Mapping):
                wait_average = queue_waits.get("average_seconds")
                wait_min = queue_waits.get("min_seconds")
                wait_max = queue_waits.get("max_seconds")
                if all(
                    isinstance(value, (int, float))
                    for value in (wait_average, wait_min, wait_max)
                ):
                    details.append(
                        (
                            f"queue wait avg {float(wait_average):.2f}s, "  # type: ignore[arg-type]
                            f"min {float(wait_min):.2f}s, max {float(wait_max):.2f}s"  # type: ignore[arg-type]
                        )
                    )
            if details:
                line += " (" + "; ".join(details) + ")"
            backlog = entry.get("backlog_count")
            try:
                backlog_int = int(backlog)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                backlog_int = 0
            if backlog_int > 0:
                line += f" [backlog: {backlog_int}]"
            lines.append(line)
    return lines


def _format_run_history(runs: list[PipelineRun]) -> list[str]:
    grouped: dict[str, list[PipelineRun]] = {}
    for run in runs:
        grouped.setdefault(run.pipeline, []).append(run)

    lines: list[str] = []
    for pipeline in sorted(grouped):
        lines.append(f"Pipeline: {pipeline}")
        entries = grouped[pipeline]
        if not entries:
            lines.append("  No runs recorded.")
            continue
        for entry in entries:
            created = entry.created_at.astimezone(timezone.utc).isoformat()
            updated = entry.updated_at.astimezone(timezone.utc).isoformat()
            details = [f"{entry.run_id} [{entry.status}]"]
            details.append(f"created {created}")
            if entry.finished_at is not None:
                finished = entry.finished_at.astimezone(timezone.utc).isoformat()
                details.append(f"finished {finished}")
            else:
                details.append(f"updated {updated}")
            if entry.duration_ms is not None:
                duration_seconds = float(entry.duration_ms) / 1000
                details.append(f"duration {duration_seconds:.2f}s")
            lines.append("  " + " | ".join(details))
    return lines


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


def _format_worker_metrics(metrics: WorkerPoolMetrics) -> str:
    limit = metrics.max_workers
    if limit is None:
        limit_display = "unbounded"
    else:
        limit_display = str(int(limit))
    return f"Active workers: {int(metrics.active_workers)} (limit: {limit_display})."


def _parse_pipeline_parameters(raw: list[str] | None) -> dict[str, str]:
    parameters: dict[str, str] = {}
    if not raw:
        return parameters
    for item in raw:
        if "=" not in item:
            msg = f"Invalid parameter '{item}'. Expected key=value pairs."
            raise ValueError(msg)
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Parameter keys cannot be empty.")
        parameters[key] = value.strip()
    return parameters


def _limit_dataset(value: Any, limit: int) -> Any:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)[:limit]
    return value


def _coerce_table_rows(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        rows: list[Mapping[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                rows.append(item)
            else:
                rows.append({"value": item})
        return rows
    return [{"value": value}]


def _format_table_rows(rows: list[Mapping[str, Any]]) -> list[str]:
    if not rows:
        return ["(no records)"]

    columns = sorted({key for row in rows for key in row.keys()})
    widths = {
        column: max(len(column), max(len(str(row.get(column, ""))) for row in rows))
        for column in columns
    }

    header = " | ".join(column.ljust(widths[column]) for column in columns)
    separator = "-+-".join("-" * widths[column] for column in columns)
    lines = [header, separator]

    for row in rows:
        lines.append(
            " | ".join(
                str(row.get(column, "")).ljust(widths[column]) for column in columns
            )
        )
    return lines


def _extract_pipeline_definitions(
    payload: Mapping[str, Any], *, source: str | None = None
) -> list[PipelineDefinition]:
    pipelines_section = payload.get("pipelines")
    if not isinstance(pipelines_section, Mapping):
        definition = _extract_pipeline_definition(payload, source=source)
        return [definition]

    if not pipelines_section:
        raise typer.BadParameter("Manifest does not contain any pipeline entries.")

    definitions: list[PipelineDefinition] = []
    for pipeline_name, config_payload in sorted(pipelines_section.items()):
        definition = _build_pipeline_definition_from_manifest(
            config_payload, pipeline_name, source=source
        )
        definitions.append(definition)
    return definitions


def _load_pipeline_manifest(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        msg = f"Pipeline manifest '{path}' does not exist."
        raise typer.BadParameter(msg)
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".toml":
        data = tomllib.loads(text)
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - optional dependency
            msg = "PyYAML is required to load YAML pipeline manifests."
            raise typer.BadParameter(msg) from exc
        data = yaml.safe_load(text) or {}
    else:
        msg = "Pipeline manifests must use TOML or YAML formats."
        raise typer.BadParameter(msg)
    if not isinstance(data, Mapping):
        msg = "Pipeline manifests must contain a mapping at the top level."
        raise typer.BadParameter(msg)
    return dict(data)


def _build_pipeline_definition_from_manifest(
    config_payload: Mapping[str, Any],
    pipeline_name: str,
    *,
    source: str | None = None,
) -> PipelineDefinition:
    pipeline_name = str(pipeline_name)
    context = source or "manifest"

    if not isinstance(config_payload, Mapping):
        msg = f"{context} pipeline '{pipeline_name}' entry must be a mapping."
        raise typer.BadParameter(msg)

    try:
        translated = translate_pipeline_manifest(dict(config_payload))
        return pipeline_definition_from_profile_entry(
            str(pipeline_name),
            translated,
        )
    except (KeyError, TypeError, ValueError) as exc:
        msg = f"{context} pipeline '{pipeline_name}': {exc}"
        raise typer.BadParameter(msg) from exc


def _extract_pipeline_definition(
    payload: Mapping[str, Any], *, name: str | None = None, source: str | None = None
) -> PipelineDefinition:
    config_payload: Mapping[str, Any]
    pipeline_name: str

    pipelines_section = payload.get("pipelines")
    if isinstance(pipelines_section, Mapping):
        if name is None:
            if len(pipelines_section) != 1:
                msg = "Manifest contains multiple pipelines; provide --name to select one."
                raise typer.BadParameter(msg)
            pipeline_name, config_payload = next(iter(pipelines_section.items()))
        else:
            try:
                config_payload = pipelines_section[name]
            except KeyError as exc:
                msg = f"Manifest does not include a pipeline named '{name}'."
                raise typer.BadParameter(msg) from exc
            pipeline_name = name
    else:
        pipeline_name = name or payload.get("name")  # type: ignore[assignment]
        if not pipeline_name:
            raise typer.BadParameter("Pipeline manifests must declare a 'name'.")
        pipeline_name = str(pipeline_name)
        if name is not None and pipeline_name != name:
            msg = (
                "Pipeline manifest name does not match the '--name' option "
                f"('{pipeline_name}' != '{name}')."
            )
            raise typer.BadParameter(msg)
        config_payload = payload

    return _build_pipeline_definition_from_manifest(
        config_payload, str(pipeline_name), source=source
    )


@pipeline_app.command("list")
def pipeline_list() -> None:
    """Display pipelines registered with the orchestrator."""

    orchestrator = get_pipeline_orchestrator()
    definitions = orchestrator.list_pipelines()
    if not definitions:
        typer.echo("No pipelines are currently registered with the orchestrator.")
        raise typer.Exit(code=0)

    for definition in definitions:
        typer.echo(_format_pipeline_definition(definition))
        if definition.description:
            typer.echo(f"  {definition.description}")
        if definition.parameters:
            params = ", ".join(sorted(definition.parameters))
            typer.echo(f"  Parameters: {params}")


@pipeline_app.command("workers")
def pipeline_workers(
    format: str = typer.Option(
        "text", "--format", help="Output format: 'text' (default) or 'json'."
    ),
) -> None:
    """Display the current worker pool utilisation."""

    output_format = _resolve_output_format(format)

    orchestrator = get_pipeline_orchestrator()
    metrics = orchestrator.worker_pool_metrics()

    payload = {
        "max_workers": metrics.max_workers,
        "active_workers": metrics.active_workers,
    }

    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(_format_worker_metrics(metrics))


@pipeline_app.command("run")
def pipeline_run(
    name: str = typer.Argument(..., help="Pipeline identifier."),
    *,
    parameters: list[str] | None = typer.Option(
        None,
        "--param",
        "-p",
        help="Key=value parameters forwarded to the orchestrator.",
    ),
) -> None:
    """Trigger a pipeline run via the orchestrator."""

    orchestrator = get_pipeline_orchestrator()
    try:
        parsed = _parse_pipeline_parameters(parameters)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    try:
        run = orchestrator.trigger_run(name, parameters=parsed)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc

    payload = run.serialise()
    typer.echo(f"Triggered pipeline '{payload['pipeline']}' (run id: {payload['id']}).")
    typer.echo(f"Current status: {payload['status']}")


@pipeline_app.command("cancel")
def pipeline_cancel(
    run_ids: list[str] = typer.Argument(
        ...,
        help="Pipeline run identifier(s) to cancel.",
        metavar="RUN_ID ...",
    ),
    *,
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Attempt to forcefully cancel running tasks if graceful cancellation "
            "is not possible."
        ),
    ),
) -> None:
    """Request cancellation of one or more pipeline runs."""

    orchestrator = get_pipeline_orchestrator()
    try:
        results = orchestrator.cancel_runs(run_ids, force=force)
    except KeyError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    failed: list[str] = []
    for run_id, cancelled in results.items():
        if cancelled:
            typer.echo(f"Cancelled run '{run_id}'.")
        else:
            failed.append(run_id)
            message = (
                f"Cancellation requested for run '{run_id}'."
                if not force
                else f"Unable to cancel run '{run_id}' despite --force."
            )
            typer.echo(message)

    if failed:
        raise typer.Exit(code=1)


@pipeline_app.command("stats")
def pipeline_stats(
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
) -> None:
    """Display aggregated run statistics from the orchestrator."""

    orchestrator = get_pipeline_orchestrator()

    parsed_since: datetime | None = None
    if since is not None:
        try:
            parsed_since = datetime.fromisoformat(since)
        except ValueError as exc:
            raise typer.BadParameter("Invalid 'since' timestamp.") from exc
        if parsed_since.tzinfo is None:
            parsed_since = parsed_since.replace(tzinfo=timezone.utc)
        else:
            parsed_since = parsed_since.astimezone(timezone.utc)

    pipeline_filter: str | None = None
    if pipeline is not None:
        pipeline_filter = pipeline.strip()
        if not pipeline_filter:
            raise typer.BadParameter("Pipeline name must not be blank.")

    stats = orchestrator.aggregate_runs(
        include_durations=include_durations,
        since=parsed_since,
        pipeline=pipeline_filter,
    )

    if not stats:
        typer.echo("No pipeline run statistics available.")
        raise typer.Exit(code=0)

    for line in _format_pipeline_statistics(stats):
        typer.echo(line)


@pipeline_app.command("history")
def pipeline_history(
    limit: int | None = typer.Option(
        None,
        "--limit",
        min=1,
        help="Maximum number of runs to return.",
    ),
    pipeline: str | None = typer.Option(
        None,
        "--pipeline",
        help="Restrict history to the specified pipeline.",
    ),
    format: str = typer.Option(
        "text",
        "--format",
        help="Output format: 'text' (default) or 'json'.",
    ),
) -> None:
    """Display recent pipeline run metadata from the orchestrator."""

    output_format = _resolve_output_format(format)

    pipeline_filter: str | None = None
    if pipeline is not None:
        pipeline_filter = pipeline.strip()
        if not pipeline_filter:
            raise typer.BadParameter("Pipeline name must not be blank.")

    orchestrator = get_pipeline_orchestrator()
    page = orchestrator.list_runs(pipeline=pipeline_filter, limit=limit)

    if output_format == "json":
        typer.echo(json.dumps(page.serialise(), indent=2))
        return

    if not page.runs:
        typer.echo("No pipeline run history available.")
        raise typer.Exit(code=0)

    for line in _format_run_history(page.runs):
        typer.echo(line)


@pipeline_app.command("prune")
def pipeline_prune(
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
) -> None:
    """Apply pipeline run retention policies and report the outcome."""

    orchestrator = get_pipeline_orchestrator()

    if max_age_hours is None and max_runs is None:
        policy = orchestrator.retention_policy
        if policy is None or not policy.configured:
            typer.echo("No retention policy configured; nothing to prune.")
            raise typer.Exit(code=0)

    max_age: timedelta | None = None
    if max_age_hours is not None:
        max_age = timedelta(hours=max_age_hours)

    result = orchestrator.prune_history(max_age=max_age, max_runs=max_runs)

    typer.echo(
        f"Removed {result.removed_runs} runs and {result.removed_events} events from the store."
    )
    typer.echo(f"{result.remaining_runs} runs remain after pruning.")
    if result.removed_runs_by_pipeline:
        details = ", ".join(
            f"{pipeline}: {count}"
            for pipeline, count in sorted(result.removed_runs_by_pipeline.items())
        )
        typer.echo(f"Per-pipeline removals: {details}.")


@pipeline_app.command("push")
def pipeline_push(
    manifest: Path = typer.Argument(..., help="TOML or YAML pipeline manifest."),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help="Pipeline name when the manifest contains multiple entries.",
    ),
) -> None:
    """Register or update a pipeline definition from a manifest file."""

    manifest_payload = _load_pipeline_manifest(manifest)
    definition = _extract_pipeline_definition(
        manifest_payload, name=name, source=str(manifest.resolve())
    )

    orchestrator = get_pipeline_orchestrator()
    created = orchestrator.upsert(definition)
    action = "created" if created else "updated"
    typer.echo(
        f"Pipeline '{definition.name}' {action} from {manifest.resolve()}.",
    )


@pipeline_app.command("validate")
def pipeline_validate(
    manifest: Path = typer.Argument(..., help="TOML or YAML pipeline manifest."),
    name: str | None = typer.Option(
        None,
        "--name",
        "-n",
        help=(
            "Pipeline name when validating a specific entry in a manifest "
            "containing multiple definitions."
        ),
    ),
) -> None:
    """Validate pipeline manifest schema without registering definitions."""

    manifest_payload = _load_pipeline_manifest(manifest)
    source = str(manifest.resolve())

    if name is None:
        definitions = _extract_pipeline_definitions(manifest_payload, source=source)
    else:
        definitions = [
            _extract_pipeline_definition(manifest_payload, name=name, source=source)
        ]

    if len(definitions) == 1:
        definition = definitions[0]
        typer.echo(
            (
                f"Pipeline '{definition.name}' manifest from {source} "
                "is valid and ready for registration."
            )
        )
        return

    names = ", ".join(definition.name for definition in definitions)
    typer.echo(
        (f"Validated {len(definitions)} pipeline manifests from {source}: " f"{names}.")
    )


@pipeline_app.command("delete")
def pipeline_delete(
    name: str = typer.Argument(..., help="Pipeline identifier to deregister."),
) -> None:
    """Remove a pipeline definition from the orchestrator."""

    orchestrator = get_pipeline_orchestrator()
    try:
        orchestrator.deregister(name)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Pipeline '{name}' deregistered from the orchestrator.")


def _load_uvicorn() -> Any:
    """Dynamically import uvicorn to keep it optional for non-web commands."""

    return import_module("uvicorn")


def _run_demo_dashboard(host: str, port: int, log_level: str) -> None:
    """Launch the demo dashboard with curated sample data."""

    os.environ.setdefault("TRAFALGAR_DASHBOARD_TOKEN", DEMO_DASHBOARD_TOKEN)
    uvicorn = _load_uvicorn()
    uvicorn.run(
        "apps.trafalgar.web.demo:app",
        host=host,
        port=port,
        reload=False,
        log_level=log_level,
    )


@web_app.command()
def dashboard(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the dashboard server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the dashboard on.",
        show_default=True,
    ),
    reload: bool = typer.Option(
        False,
        "--reload/--no-reload",
        help="Automatically reload when source files change.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
    demo_port: Optional[int] = typer.Option(
        None,
        "--demo-port",
        min=1,
        max=65535,
        help=(
            "Launch a second dashboard instance populated with demo data on the "
            "specified port. The demo service reuses the same host and "
            "disables auto-reload."
        ),
    ),
    open_browser: bool = typer.Option(
        False,
        "--open-browser/--no-open-browser",
        help="Launch the Trafalgar dashboard in the default web browser.",
        show_default=True,
    ),
    browser_path: Optional[str] = typer.Option(
        None,
        "--browser-path",
        help=(
            "Optional browser path or alias passed to `webbrowser.get()` "
            "when launching the dashboard URL."
        ),
    ),
) -> None:
    """Launch the OnePiece web dashboard using uvicorn."""

    if demo_port is not None and demo_port == port:
        raise typer.BadParameter(
            "Demo port must differ from the primary dashboard port."
        )

    dashboard_url = f"http://{host}:{port}"
    demo_process: Process | None = None
    if demo_port is not None:
        typer.echo(
            "Starting Trafalgar demo dashboard on "
            f"http://{host}:{demo_port} (token: {DEMO_DASHBOARD_TOKEN})"
        )
        demo_process = Process(
            target=_run_demo_dashboard,
            args=(host, demo_port, log_level),
            daemon=True,
        )
        demo_process.start()

    if open_browser:
        try:
            browser_controller = (
                webbrowser.get(browser_path)
                if browser_path is not None
                else webbrowser.get()
            )
        except webbrowser.Error as error:
            typer.echo(
                "Unable to resolve a browser for the Trafalgar dashboard: " f"{error}",
                err=True,
            )
        else:

            def _open_dashboard(label: str, url: str) -> None:
                typer.echo(f"Opening {label} in a web browser at {url}")
                try:
                    browser_controller.open(url, new=2)
                except webbrowser.Error as error:
                    typer.echo(
                        f"Unable to launch the {label} browser window: {error}",
                        err=True,
                    )

            _open_dashboard("Trafalgar dashboard", dashboard_url)

            if demo_port is not None:
                demo_url = f"http://{host}:{demo_port}"
                _open_dashboard("Trafalgar demo dashboard", demo_url)

    typer.echo(f"Starting OnePiece dashboard on {dashboard_url}")
    uvicorn = _load_uvicorn()
    try:
        uvicorn.run(
            "apps.trafalgar.web.dashboard:app",
            host=host,
            port=port,
            reload=reload,
            log_level=log_level,
        )
    finally:
        if demo_process is not None:
            typer.echo("Stopping Trafalgar demo dashboard")
            demo_process.terminate()
            demo_process.join(timeout=5)


def _serve_ingest(*, host: str, port: int, reload: bool, log_level: str) -> None:
    """Launch the ingest runs API using uvicorn."""

    typer.echo(f"Starting OnePiece ingest API on http://{host}:{port}")
    uvicorn = _load_uvicorn()
    uvicorn.run(
        "apps.trafalgar.web.ingest:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


def _serve_render(*, host: str, port: int, reload: bool, log_level: str) -> None:
    """Launch the render submission API using uvicorn."""

    typer.echo(f"Starting OnePiece render API on http://{host}:{port}")
    uvicorn = _load_uvicorn()
    uvicorn.run(
        "apps.trafalgar.web.render:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


def _serve_review(*, host: str, port: int, reload: bool, log_level: str) -> None:
    """Launch the review API using uvicorn."""

    typer.echo(f"Starting OnePiece review API on http://{host}:{port}")
    uvicorn = _load_uvicorn()
    uvicorn.run(
        "apps.trafalgar.web.review:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


def _serve_pipeline(*, host: str, port: int, reload: bool, log_level: str) -> None:
    """Launch the pipeline API using uvicorn."""

    typer.echo(f"Starting OnePiece pipeline API on http://{host}:{port}")
    uvicorn = _load_uvicorn()
    uvicorn.run(
        "apps.trafalgar.web.pipeline:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


@web_app.command("ingest")
def web_ingest(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the ingest API server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the ingest API on.",
        show_default=True,
    ),
    reload: bool = typer.Option(
        False,
        "--reload/--no-reload",
        help="Automatically reload when source files change.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
) -> None:
    """Launch the ingest API via the web command group."""

    _serve_ingest(host=host, port=port, reload=reload, log_level=log_level)


@web_app.command("render")
def web_render(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the render API server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the render API on.",
        show_default=True,
    ),
    reload: bool = typer.Option(
        False,
        "--reload/--no-reload",
        help="Automatically reload when source files change.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
) -> None:
    """Launch the render submission API via the web command group."""

    _serve_render(host=host, port=port, reload=reload, log_level=log_level)


@web_app.command("review")
def web_review(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the review API server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the review API on.",
        show_default=True,
    ),
    reload: bool = typer.Option(
        False,
        "--reload/--no-reload",
        help="Automatically reload when source files change.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
) -> None:
    """Launch the review API via the web command group."""

    _serve_review(host=host, port=port, reload=reload, log_level=log_level)


@web_app.command("pipeline")
def web_pipeline(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the pipeline API server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the pipeline API on.",
        show_default=True,
    ),
    reload: bool = typer.Option(
        False,
        "--reload/--no-reload",
        help="Automatically reload when source files change.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
) -> None:
    """Launch the pipeline API via the web command group."""

    _serve_pipeline(host=host, port=port, reload=reload, log_level=log_level)


@ingest_app.callback()
def ingest(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the ingest API server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the ingest API on.",
        show_default=True,
    ),
    reload: bool = typer.Option(
        False,
        "--reload/--no-reload",
        help="Automatically reload when source files change.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        "info",
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
) -> None:
    """Launch the ingest runs API using uvicorn."""

    _serve_ingest(host=host, port=port, reload=reload, log_level=log_level)


@ingest_app.command("dry-run")
def ingest_dry_run(
    source: str | None = typer.Option(
        None,
        "--source",
        "-s",
        help="Name of the ingestion source to preview. Defaults to the registered default.",
    ),
    limit: int = typer.Option(
        5,
        "--limit",
        "-n",
        min=1,
        help="Maximum number of records to display per dataset.",
        show_default=True,
    ),
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Output format: 'text' (table) or 'json'.",
        callback=lambda value: _resolve_output_format(value),
        show_default=True,
    ),
) -> None:
    """Preview ingest source output without persisting it."""

    registry = initialize_providers()
    try:
        provider = (
            registry.create("reconcile", source)
            if source is not None
            else registry.create_default("reconcile")
        )
    except ProviderNotFoundError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)

    if not isinstance(provider, ReconcileDataProvider):
        typer.echo("Selected provider is not a reconcile data provider.")
        raise typer.Exit(code=1)

    payload = provider.load()
    limited_payload = {
        key: _limit_dataset(value, limit) for key, value in payload.items()
    }

    if output_format == "json":
        typer.echo(json.dumps(limited_payload, indent=2, default=str))
        return

    for dataset, data in limited_payload.items():
        typer.echo(f"{dataset}:")
        for line in _format_table_rows(_coerce_table_rows(data)):
            typer.echo(f"  {line}")
        typer.echo()


@auth_app.command("generate-token")
def auth_generate_token(
    write_to: Optional[Path] = typer.Option(
        None,
        "--write-to",
        help="Optional path to persist the generated token with 0600 permissions.",
    ),
) -> None:
    """Generate a bearer token for the dashboard APIs."""

    token = secrets.token_urlsafe(32)

    typer.echo("Generated Trafalgar dashboard token:\n")
    typer.echo(token)
    typer.echo(
        "\nExport it with:\n" "  export TRAFALGAR_DASHBOARD_TOKEN='" f"{token}" "'\n"
    )

    if write_to is not None:
        write_to.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(write_to, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(token)
            file.write("\n")
        os.chmod(write_to, 0o600)
        typer.echo(f"Token written to {write_to} with 0600 permissions.")


app.add_typer(web_app)
app.add_typer(ingest_app)
app.add_typer(auth_app)
app.add_typer(pipeline_app)
