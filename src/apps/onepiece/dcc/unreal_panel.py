from __future__ import annotations

from pathlib import Path

import structlog
import typer

from libraries.creative.dcc.unreal import deploy as unreal_deploy
from libraries.creative.dcc.unreal.scripts import discover_unreal_scripts

log = structlog.get_logger(__name__)

app = typer.Typer(name="unreal-panel", help="Unreal panel deployment commands")


@app.command("list-scripts")
def list_scripts() -> None:
    """Print the bundled scripts that will appear in Unreal menus."""

    scripts = discover_unreal_scripts(unreal_deploy.get_script_library_path())
    if not scripts:
        typer.echo("No bundled scripts found.")
        return

    typer.echo("Bundled Unreal scripts:")
    for script in scripts:
        typer.echo(f"- {script.label} ({script.path.name})")


@app.command("deploy")
def deploy(
    target: Path = typer.Option(
        unreal_deploy.DEFAULT_DEPLOY_PATH,
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
    """Copy the OnePiece Unreal integration into a plugin directory."""

    destination = unreal_deploy.deploy_unreal_resources(target, overwrite=overwrite)
    log.info("unreal.deploy.cli_completed", destination=str(destination))
    typer.echo(f"Deployed OnePiece Unreal panel and scripts to {destination}")


__all__ = ["app", "deploy", "list_scripts"]
