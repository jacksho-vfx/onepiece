"""Typer CLI entry points for the Trafalgar dashboard services."""

from importlib import import_module
from multiprocessing import Process
from pathlib import Path
from typing import Any, Mapping, Optional

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
            import yaml  # type: ignore[import-not-found]
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


def _extract_pipeline_definition(
    payload: Mapping[str, Any], *, name: str | None = None
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
        if not isinstance(config_payload, Mapping):
            msg = "Pipeline entries must be mappings."
            raise typer.BadParameter(msg)
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

    try:
        return pipeline_definition_from_profile_entry(
            str(pipeline_name),
            dict(config_payload),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc


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
    definition = _extract_pipeline_definition(manifest_payload, name=name)

    orchestrator = get_pipeline_orchestrator()
    created = orchestrator.upsert(definition)
    action = "created" if created else "updated"
    typer.echo(
        f"Pipeline '{definition.name}' {action} from {manifest.resolve()}.",
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


@auth_app.command("generate-token")
def auth_generate_token(
    write_to: Optional[Path] = typer.Option(
        None,
        "--write-to",
        help="Optional path to persist the generated token with 0600 permissions.",
    )
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
