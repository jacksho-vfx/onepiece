"""Typer CLI to launch the Uta web GUI."""

from __future__ import annotations

from importlib import import_module
import webbrowser
from typing import Any

import typer

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8050

app = typer.Typer(name="uta", help="Browser GUI for the OnePiece toolchain.")


def _load_uvicorn() -> Any:
    return import_module("uvicorn")


@app.command()
def serve(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Host interface to bind the server to.",
        show_default=True,
    ),
    port: int = typer.Option(
        DEFAULT_PORT,
        "--port",
        "-p",
        min=1,
        max=65535,
        help="Port to expose the Uta GUI on.",
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
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-browser",
        help="Open the GUI in the default browser after starting.",
        show_default=True,
    ),
) -> None:
    """Launch the Uta GUI server using uvicorn."""

    typer.echo(f"Starting Uta on http://{host}:{port}")
    if open_browser:
        try:  # pragma: no cover - depends on environment
            webbrowser.open(f"http://{host}:{port}")
        except webbrowser.Error:
            typer.echo("Unable to open browser automatically.", err=True)
    uvicorn = _load_uvicorn()
    uvicorn.run(
        "apps.uta.web:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


__all__ = ["app", "serve"]
