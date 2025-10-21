"""Typer CLI entry points for the Perona dashboard services."""

import json
import os
from dataclasses import asdict
from importlib import import_module
from pathlib import Path
from typing import Any, Literal, Mapping

import typer

from apps.perona.engine import DEFAULT_SETTINGS_PATH, PeronaEngine
from apps.perona.version import PERONA_VERSION

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8065

OutputFormat = Literal["table", "json"]

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


def _format_value(value: object) -> str:
    """Render numeric values with thousands separators where possible."""

    if isinstance(value, float):
        return f"{value:,}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _humanise_key(key: str) -> str:
    """Convert snake_case keys into a more readable variant."""

    overrides = {"gpu": "GPU", "gb": "GB", "ms": "ms", "pnl": "P&L"}
    words = key.split("_")
    return " ".join(overrides.get(word, word.capitalize()) for word in words)


def _resolve_settings_path(cli_path: Path | None) -> Path | None:
    """Return the first existing settings candidate for display purposes."""

    candidates: list[Path] = []
    if cli_path is not None:
        candidates.append(cli_path)
    env_path = os.getenv("PERONA_SETTINGS_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_SETTINGS_PATH)

    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved
    return None


def _format_settings_table(
    baseline: Mapping[str, object],
    target_error_rate: float,
    pnl_baseline_cost: float,
    *,
    settings_path: Path | None,
) -> str:
    """Produce a readable summary of the resolved Perona settings."""

    humanised_keys = {key: _humanise_key(key) for key in baseline}
    width = max(
        [len(name) for name in humanised_keys.values()]
        + [len("Target error rate"), len("P&L baseline cost")]
    )
    lines: list[str] = []
    if settings_path is not None:
        lines.append(f"Settings file: {settings_path}")
        lines.append("")
    lines.append("Baseline cost inputs")
    lines.append("-" * len("Baseline cost inputs"))
    for key, value in baseline.items():
        display_key = humanised_keys[key]
        lines.append(f"{display_key:<{width}} : {_format_value(value)}")
    lines.append("")
    lines.append(f"{'Target error rate':<{width}} : {_format_value(target_error_rate)}")
    lines.append(f"{'P&L baseline cost':<{width}} : {_format_value(pnl_baseline_cost)}")
    return "\n".join(lines)


@app.command("settings")
def settings(
    settings_path: Path | None = typer.Option(
        None,
        "--settings-path",
        help="Optional path to a Perona settings file to load.",
    ),
    output_format: OutputFormat = typer.Option(
        "table",
        "--format",
        "-f",
        help="Output format for the resolved settings (table or json).",
        case_sensitive=False,
    ),
) -> None:
    """Display the resolved Perona configuration values."""

    resolved_path = _resolve_settings_path(settings_path)
    engine = PeronaEngine.from_settings(path=settings_path)
    baseline = asdict(engine.baseline_cost_input)
    payload: dict[str, object] = {
        "baseline_cost_input": baseline,
        "target_error_rate": engine.target_error_rate,
        "pnl_baseline_cost": engine.pnl_baseline_cost,
    }
    if resolved_path is not None:
        payload["settings_path"] = str(resolved_path)

    fmt = str(output_format).lower()
    if fmt not in {"table", "json"}:
        raise typer.BadParameter("format must be either 'table' or 'json'.")

    if fmt == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    typer.echo(
        _format_settings_table(
            baseline,
            engine.target_error_rate,
            engine.pnl_baseline_cost,
            settings_path=resolved_path,
        )
    )


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
