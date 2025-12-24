"""Utilities for deploying OnePiece tooling into 3ds Max."""

from __future__ import annotations

from pathlib import Path

import structlog
import typer

from libraries.creative.dcc.max import deploy as max_deploy

log = structlog.get_logger(__name__)

app = typer.Typer(name="max", help="3ds Max panel deployment commands")


@app.command("list-scripts")
def list_scripts() -> None:
    """Print the bundled MaxScript files that populate the menu and panel."""

    scripts = max_deploy.available_script_files()
    if not scripts:
        typer.echo("No bundled 3ds Max scripts found.")
        return

    typer.echo("Bundled 3ds Max scripts:")
    for script in scripts:
        typer.echo(f"- {script.name}")


@app.command("deploy")
def deploy(
    target: Path = typer.Option(
        max_deploy.DEFAULT_DEPLOY_PATH,
        "--target",
        "-t",
        help="Where to copy menu.ms and the bundled MaxScripts.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        "-f",
        help="Replace an existing deployment at the target location.",
    ),
) -> None:
    """Copy the OnePiece 3ds Max integration into the user scripts folder."""

    destination = max_deploy.deploy_max_resources(target, overwrite=overwrite)
    log.info("max.deploy.cli_completed", destination=str(destination))
    typer.echo(f"Deployed OnePiece 3ds Max panel and menu to {destination}")


__all__ = ["app", "deploy", "list_scripts"]
