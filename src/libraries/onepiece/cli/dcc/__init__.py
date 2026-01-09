"""Top-level Typer application exposing DCC utilities."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog
import typer

from .animation import app as animation
from .cinema4d import app as cinema4d
from .maya_panel import app as maya
from .max import app as max_app
from .nuke import app as nuke
from .open_shot import app as open_shot
from .publish import app as publish
from .unreal_import import app as unreal_import
from .unreal_panel import app as unreal_panel
from libraries.creative.dcc import max as max_deploy
from libraries.creative.dcc import maya as maya_deploy
from libraries.creative.dcc import nuke as nuke_deploy
from libraries.creative.dcc import unreal as unreal_deploy


log = structlog.get_logger(__name__)

app = typer.Typer(name="dcc", help="DCC integration commands")

app.add_typer(animation)
app.add_typer(cinema4d)
app.add_typer(maya)
app.add_typer(max_app)
app.add_typer(nuke)
app.add_typer(open_shot)
app.add_typer(publish)
app.add_typer(unreal_import)
app.add_typer(unreal_panel)


def conform(*, profile: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Record conform operations initiated by pipeline automation."""

    log.info("dcc.conform", profile=profile)
    return {"profile": profile, "parameters": dict(kwargs)}


@app.command("deploy-all")
def deploy_all(
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        "-f",
        help=(
            "Replace existing DCC deployments instead of aborting when a target folder "
            "already exists."
        ),
    )
) -> None:
    """Deploy bundled panels and menus to all supported DCCs using default paths."""

    deployments: tuple[tuple[str, Callable[..., Path], Path], ...] = (
        (
            "Maya",
            maya_deploy.deploy.deploy_maya_resources,
            maya_deploy.deploy.DEFAULT_DEPLOY_PATH,
        ),
        (
            "Nuke",
            nuke_deploy.deploy.deploy_nuke_resources,
            nuke_deploy.deploy.DEFAULT_DEPLOY_PATH,
        ),
        (
            "3ds Max",
            max_deploy.deploy.deploy_max_resources,
            max_deploy.deploy.DEFAULT_DEPLOY_PATH,
        ),
        (
            "Unreal",
            unreal_deploy.deploy.deploy_unreal_resources,
            unreal_deploy.deploy.DEFAULT_DEPLOY_PATH,
        ),
    )

    for name, deploy_func, default_target in deployments:
        typer.echo(f"Deploying {name} resources to {default_target}...")
        try:
            destination = deploy_func(default_target, overwrite=overwrite)
        except FileExistsError as exc:
            typer.secho(
                (
                    f"{name} destination '{default_target}' already exists. "
                    "Re-run with --overwrite to replace it."
                ),
                fg=typer.colors.RED,
            )
            log.warning(
                "dcc.deploy_all.exists", dcc=name, destination=str(default_target)
            )
            raise typer.Exit(code=1) from exc

        log.info("dcc.deploy_all.completed", dcc=name, destination=str(destination))
        typer.secho(
            f"Deployed {name} panel and menu resources to {destination}",
            fg=typer.colors.GREEN,
        )

    typer.echo("All DCC panels and menus deployed successfully.")


__all__ = [
    "app",
    "animation",
    "cinema4d",
    "maya",
    "max_app",
    "nuke",
    "open_shot",
    "publish",
    "unreal_import",
    "unreal_panel",
    "deploy_all",
    "conform",
]
