"""Typer commands for Cinema 4D package workflows."""

from __future__ import annotations

from pathlib import Path

import structlog
import typer

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


__all__ = ["app", "validate"]
