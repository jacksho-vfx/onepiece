"""Utilities for deploying OnePiece tooling into Maya."""

from __future__ import annotations

from pathlib import Path

import structlog
import typer

from libraries.creative.dcc.maya import deploy as maya_deploy

log = structlog.get_logger(__name__)

app = typer.Typer(name="maya", help="Maya panel deployment commands")


@app.command("list-scripts")
def list_scripts() -> None:
    """Print the bundled scripts that will appear in Maya menus and panels."""

    scripts = maya_deploy.available_script_files()
    if not scripts:
        typer.echo("No bundled Maya scripts found.")
        return

    typer.echo("Bundled Maya scripts:")
    for script in scripts:
        typer.echo(f"- {script.name}")


@app.command("deploy")
def deploy(
    target: Path = typer.Option(
        maya_deploy.DEFAULT_DEPLOY_PATH,
        "--target",
        "-t",
        help="Where to copy userSetup.py, the menu, and bundled scripts.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        "-f",
        help="Replace an existing deployment at the target location.",
    ),
) -> None:
    """Copy the OnePiece Maya integration into the scripts directory."""

    destination = maya_deploy.deploy_maya_resources(target, overwrite=overwrite)
    log.info("maya.deploy.cli_completed", destination=str(destination))
    typer.echo(f"Deployed OnePiece Maya panel, menu, and scripts to {destination}")


__all__ = ["app", "deploy", "list_scripts"]
