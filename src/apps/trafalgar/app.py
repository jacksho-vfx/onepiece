"""Typer CLI entry points for the Trafalgar dashboard services."""

from importlib import import_module
from typing import Any

import typer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

app = typer.Typer(name="trafalgar", help="Operations for the Trafalgar dashboard.")
web_app = typer.Typer(name="web", help="Web interface helpers.")
ingest_app = typer.Typer(
    name="ingest",
    help="Ingestion helper application.",
    invoke_without_command=True,
)


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


app.add_typer(web_app)
app.add_typer(ingest_app)
