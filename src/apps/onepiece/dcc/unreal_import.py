"""CLI for importing published Maya packages into Unreal Engine."""

from __future__ import annotations

import json
from pathlib import Path

import structlog
import typer

from apps.onepiece.utils.errors import OnePieceExternalServiceError
from libraries.creative.dcc.maya.unreal_importer import (
    UnrealImportError,
    UnrealPackageImporter,
)


log = structlog.get_logger(__name__)

app = typer.Typer(help="Unreal Engine DCC integration commands.")


def _format_summary(summaries: list[object]) -> str:
    return json.dumps(summaries, indent=2, sort_keys=True)


@app.command("import-unreal")
def import_unreal(
    package: Path = typer.Option(
        ...,
        "--package",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        help="Path to the published package directory.",
    ),
    project: str = typer.Option(..., "--project", help="Unreal project identifier."),
    asset: str = typer.Option(..., "--asset", help="Asset name for import."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--execute",
        help="Print the planned import tasks without invoking Unreal.",
    ),
) -> None:
    """Import a Maya-authored package into an Unreal project."""

    importer = UnrealPackageImporter()

    try:
        summaries = importer.import_package(
            package,
            project=project,
            asset_name=asset,
            dry_run=dry_run,
        )
    except UnrealImportError as exc:
        log.error(
            "unreal_cli_import_failed",
            project=project,
            asset=asset,
            package=str(package),
            error=str(exc),
        )
        raise OnePieceExternalServiceError(
            f"Failed to import {asset} into Unreal project {project}: {exc}"
        ) from exc

    if dry_run:
        typer.echo(_format_summary([summary.to_dict() for summary in summaries]))
        return

    typer.echo(
        f"Imported {len(summaries)} assets into Unreal project {project} for {asset}"
    )


__all__ = ["app", "import_unreal"]
