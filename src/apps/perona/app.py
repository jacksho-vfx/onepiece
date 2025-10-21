"""Typer CLI entry points for the Perona dashboard services."""

import os
from importlib import import_module
from pathlib import Path
from typing import Any

import typer

from apps.perona.version import PERONA_VERSION

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8065
DEFAULT_SETTINGS_FILE = Path(__file__).with_name("defaults.toml")

app = typer.Typer(
    name="perona",
    help=(
        "Operations for the Perona VFX performance dashboard. Use `perona web dashboard` "
        "to launch the FastAPI service that powers the real-time analytics surface."
    ),
)
web_app = typer.Typer(name="web", help="Web interface helpers for Perona.")
app.add_typer(web_app)


@app.command("version")
def version() -> None:
    """Display the current Perona release version."""

    typer.echo(PERONA_VERSION)


def _load_uvicorn() -> Any:
    """Dynamically import uvicorn to keep it optional for non-web commands."""

    try:
        return import_module("uvicorn")
    except ImportError as exc:
        raise typer.BadParameter(
            "uvicorn is required for this command. Install it with "
            "`pip install onepiece[uvicorn]`."
        ) from exc


def _resolve_settings_file() -> Path:
    """Return the active Perona settings file path."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_SETTINGS_FILE


@app.command("settings")
def settings(
    show_path: bool = typer.Option(
        False,
        "--show-path",
        help="Show the resolved settings path instead of the file contents.",
    )
) -> None:
    """Display the contents (or path) of the active Perona settings file."""

    settings_file = _resolve_settings_file()

    if show_path:
        typer.echo(str(settings_file))
        return

    if not settings_file.exists():
        typer.echo(
            f"Settings file not found at {settings_file}. Set PERONA_SETTINGS_PATH to a valid file."
        )
        raise typer.Exit(code=1)

    typer.echo(settings_file.read_text())


@web_app.command("dashboard")
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
        help="Port to expose the Perona dashboard on.",
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
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file loaded by the dashboard.",
    ),
) -> None:
    """Launch the Perona dashboard using uvicorn."""

    typer.echo(f"Starting Perona dashboard on http://{host}:{port}")
    uvicorn = _load_uvicorn()

    if settings_path is not None:
        os.environ["PERONA_SETTINGS_PATH"] = str(settings_path)
    else:
        os.environ.pop("PERONA_SETTINGS_PATH", None)

    uvicorn.run(
        "apps.perona.web.dashboard:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


__all__ = ["app", "dashboard", "settings", "version"]
