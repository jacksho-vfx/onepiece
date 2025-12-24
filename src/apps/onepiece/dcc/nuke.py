"""Utilities for deploying OnePiece tooling into Nuke."""

from __future__ import annotations

from pathlib import Path

import structlog
import typer

from libraries.creative.dcc.nuke import deploy as nuke_deploy

log = structlog.get_logger(__name__)

app = typer.Typer(name="nuke", help="Nuke panel deployment commands")


@app.command("list-scripts")
def list_scripts() -> None:
    """Print the bundled scripts that will appear in Nuke menus."""

    scripts = nuke_deploy.available_script_files()
    if not scripts:
        typer.echo("No bundled scripts found.")
        return

    typer.echo("Bundled scripts:")
    for script in scripts:
        typer.echo(f"- {script.name}")


@app.command("deploy")
def deploy(
    target: Path = typer.Option(
        nuke_deploy.DEFAULT_DEPLOY_PATH,
        "--target",
        "-t",
        help="Where to copy menu.py and the bundled scripts.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        "-f",
        help="Replace an existing deployment at the target location.",
    ),
) -> None:
    """Copy the OnePiece Nuke integration into a plugin directory."""

    destination = nuke_deploy.deploy_nuke_resources(target, overwrite=overwrite)
    log.info("nuke.deploy.cli_completed", destination=str(destination))
    typer.echo(f"Deployed OnePiece Nuke panel and menu to {destination}")
