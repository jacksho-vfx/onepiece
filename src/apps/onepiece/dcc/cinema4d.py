"""Typer commands for Cinema 4D package workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import typer

from libraries.creative.dcc.cinema4d.metadata import (
    SUMMARY_ENV_VAR,
    load_cinema4d_summary,
)
from libraries.creative.dcc.cinema4d.validation import validate_package


log = structlog.get_logger(__name__)
app = typer.Typer(name="cinema4d", help="Cinema 4D integration commands")


def _format_issues(issues: list[str]) -> str:
    """Return a human readable bullet list for validation issues."""

    bullets = "\n".join(f"- {entry}" for entry in issues)
    return (
        f"Cinema 4D package validation detected issues:\n{bullets}" if bullets else ""
    )


@app.command()
def validate(
    package_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Path to the Cinema 4D package directory",
    ),
) -> None:
    """Validate a packaged Cinema 4D scene directory."""

    log.info("cinema4d.validate.start", package=str(package_dir))
    issues = list(validate_package(package_dir))

    if not issues:
        message = f"Cinema 4D package at {package_dir} passed validation."
        typer.secho(message, fg=typer.colors.GREEN)
        log.info("cinema4d.validate.success", package=str(package_dir))
        return

    typer.secho(_format_issues(issues), fg=typer.colors.RED)
    log.error("cinema4d.validate.failed", package=str(package_dir), issues=issues)
    raise typer.Exit(code=1)


def _format_frame_range(frame_range: Any) -> str:
    if frame_range is None:
        return "Not specified"

    if isinstance(frame_range, (list, tuple)) and len(frame_range) == 2:
        start, end = frame_range
        return f"{start} - {end}"

    return str(frame_range)


@app.command("show-summary")
def show_summary(
    summary_path: Path | None = typer.Argument(
        None,
        help=(
            "Optional path to a Cinema 4D summary JSON file. When omitted the value "
            f"is resolved from ${SUMMARY_ENV_VAR}."
        ),
    ),
) -> None:
    """Display the Cinema 4D metadata summary parsed from disk."""

    log.info(
        "cinema4d.show_summary.start",
        summary_path=str(summary_path) if summary_path is not None else None,
    )

    env_override: dict[str, str] | None = None
    if summary_path is not None:
        env_override = {SUMMARY_ENV_VAR: str(summary_path)}

    summary = load_cinema4d_summary(env=env_override)
    if not summary:
        message = "No Cinema 4D summary metadata is available."
        typer.secho(message, fg=typer.colors.RED)
        log.warning("cinema4d.show_summary.missing")
        raise typer.Exit(code=1)

    frame_range = _format_frame_range(summary.get("frame_range"))
    renderer = summary.get("renderer") or "Not specified"
    take = summary.get("take") or "Not specified"
    extras = {
        key: value
        for key, value in summary.items()
        if key not in {"frame_range", "renderer", "take"}
    }

    lines = [
        "Cinema 4D Summary",
        f"  Frame range: {frame_range}",
        f"  Renderer: {renderer}",
        f"  Take: {take}",
    ]

    if extras:
        lines.append("  Extra metadata:")
        for key in sorted(extras):
            value = extras[key]
            lines.append(f"    {key}: {value}")

    typer.echo("\n".join(lines))
    log.info("cinema4d.show_summary.success", summary_keys=sorted(summary))


__all__ = ["app", "validate", "show_summary"]
