"""Typer CLI entry points for the Trafalgar dashboard services."""

from importlib import import_module
from pathlib import Path
from typing import Any, Optional

import os
import secrets

import typer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

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


def _load_uvicorn() -> Any:
    """Dynamically import uvicorn to keep it optional for non-web commands."""

    return import_module("uvicorn")


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
) -> None:
    """Launch the OnePiece web dashboard using uvicorn."""

    typer.echo(f"Starting OnePiece dashboard on http://{host}:{port}")
    uvicorn = _load_uvicorn()
    uvicorn.run(
        "apps.trafalgar.web.dashboard:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


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
        path_type=Path,
        help="Optional path to persist the generated token with 0600 permissions.",
    )
) -> None:
    """Generate a bearer token for the dashboard APIs."""

    token = secrets.token_urlsafe(32)

    typer.echo("Generated Trafalgar dashboard token:\n")
    typer.echo(token)
    typer.echo(
        "\nExport it with:\n"
        "  export TRAFALGAR_DASHBOARD_TOKEN='"
        f"{token}"
        "'\n"
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
