import typer
from onepiece.validations.naming import (
    validate_show_name,
    validate_episode_name,
    validate_scene_name,
    validate_shot,
    validate_shot_name,
    validate_asset_name,
)


app = typer.Typer(help="Validate names")


@app.command("names")
def validate_names(
    show: str, episode: str, scene: str, shot: str, asset: str | None = None
):
    """
    Validate naming conventions for show, episode, scene, shot, and optional asset.

    - Shot name is derived as epXXX_scXX_XXXX
    - Asset name is derived as epXXX_scXX_XXXX_asset
    """
    all_ok = True

    if not validate_show_name(show):
        typer.echo(f"Invalid show name: {show}")
        all_ok = False
    if not validate_episode_name(episode):
        typer.echo(f"Invalid episode name: {episode}")
        all_ok = False
    if not validate_scene_name(scene):
        typer.echo(f"Invalid scene name: {scene}")
        all_ok = False
    if not validate_shot(shot):
        typer.echo(f"Invalid shot number: {shot}")
        all_ok = False

    shot_name = f"{episode}_{scene}_{shot}"
    if not validate_shot_name(shot_name):
        typer.echo(f"Invalid shot name: {shot_name}")
        all_ok = False

    if asset:
        asset_name = f"{shot_name}_{asset}"
        if not validate_asset_name(asset_name):
            typer.echo(f"Invalid asset name: {asset_name}")
            all_ok = False

    if not all_ok:
        raise typer.Exit(code=1)
    typer.echo("All names are valid.")
