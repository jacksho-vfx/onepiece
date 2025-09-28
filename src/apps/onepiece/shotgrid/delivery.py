"""CLI helpers for preparing ShotGrid playlist deliveries."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import structlog
import typer
from upath import UPath

from src.apps.onepiece.utils.errors import OnePieceError
from src.libraries.shotgrid.client import ShotgridClient
from src.libraries.shotgrid.playlist_delivery import (
    Recipient,
    package_playlist_for_mediashuttle,
)

log = structlog.get_logger(__name__)

app = typer.Typer(help="ShotGrid delivery utilities.")


@app.command("package-playlist")
def package_playlist_command(
    project: str = typer.Option(..., "--project", "-p", help="ShotGrid project name"),
    playlist: str = typer.Option(
        ..., "--playlist", "-l", help="ShotGrid playlist name"
    ),
    destination: Path = typer.Option(
        Path.cwd(),
        "--destination",
        "-d",
        file_okay=False,
        help="Directory where the MediaShuttle package will be created.",
    ),
    recipient: str = typer.Option(
        "client",
        "--recipient",
        "-r",
        help="Recipient for the package: 'client' or 'vendor'.",
        case_sensitive=False,
    ),
) -> None:
    """Package the media referenced by a ShotGrid playlist."""

    normalized_recipient = recipient.lower()
    if normalized_recipient not in {"client", "vendor"}:
        raise OnePieceError("Recipient must be either 'client' or 'vendor'.")

    sg_client = ShotgridClient()
    package_destination = UPath(destination).expanduser()

    try:
        summary = package_playlist_for_mediashuttle(
            sg_client,
            project_name=project,
            playlist_name=playlist,
            destination=package_destination,
            recipient=cast(Recipient, normalized_recipient),
        )
    except Exception as exc:  # noqa: BLE001
        log.error(
            "package_playlist.failed",
            project=project,
            playlist=playlist,
            error=str(exc),
        )
        raise OnePieceError(str(exc)) from exc

    log.info(
        "package_playlist.success",
        project=project,
        playlist=playlist,
        package=str(summary.package_path),
    )
    typer.echo(f"Package created at {summary.package_path}")
