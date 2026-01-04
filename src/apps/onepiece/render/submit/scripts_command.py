"""Typer command for generating render submission helper scripts."""

from __future__ import annotations

from pathlib import Path

import typer

from .helpers import DCC_CHOICES, FARM_CHOICES
from .scripts import build_render_script_bundle, write_render_script_bundle


def generate_scripts(
    *,
    dcc: str = typer.Option(
        ..., "--dcc", help="Target DCC for the generated scripts.", case_sensitive=False
    ),
    farm: str = typer.Option(
        ..., "--farm", help="Render farm adapter to target.", case_sensitive=False
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Optional profile providing optimisation defaults.",
    ),
    output: Path = typer.Option(
        Path("./render_scripts"),
        "--output",
        help="Directory where the scripts should be written.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace existing scripts instead of aborting when files already exist.",
    ),
) -> None:
    """Write panel/menu submission helpers and optimisation stubs to disk."""

    dcc = dcc.lower()
    farm = farm.lower()

    if dcc not in DCC_CHOICES:
        raise typer.BadParameter(f"Unknown DCC '{dcc}'.")
    if farm not in FARM_CHOICES:
        raise typer.BadParameter(f"Unknown render farm '{farm}'.")

    bundle = build_render_script_bundle(dcc=dcc, farm=farm, profile=profile)

    try:
        written = write_render_script_bundle(bundle, output, overwrite=overwrite)
    except FileExistsError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho(f"Render submission helpers written to {output}", fg=typer.colors.GREEN)
    for path in written:
        typer.echo(f"- {path.name}")


__all__ = ["generate_scripts"]
