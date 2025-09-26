from __future__ import annotations

import csv
from pathlib import Path

import structlog
import typer
from typer import progressbar

from libraries.shotgrid.show_setup import setup_single_shot

log = structlog.get_logger(__name__)
app = typer.Typer(help="Show setup commands for ShotGrid.")


def _parse_csv(csv_path: Path) -> list[str]:
    """Return the list of shot codes defined in ``csv_path``."""

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise typer.BadParameter("CSV file must include a header row.")

        column = next(
            (
                name
                for name in reader.fieldnames
                if name and name.lower() in {"shot", "code", "name"}
            ),
            None,
        )
        if column is None:
            raise typer.BadParameter(
                "CSV must contain a 'shot', 'code', or 'name' column."
            )

        shots = [row[column].strip() for row in reader if row.get(column)]
        if not shots:
            raise typer.BadParameter("CSV does not contain any shot entries.")
        return shots


@app.command("show-setup")
def show_setup_command(
    csv: Path, project: str, template: str | None = typer.Option(None)
) -> None:
    """
    Create a ShotGrid project and hierarchy from a CSV of shots.
    """
    shots = _parse_csv(csv)
    typer.echo(f"Creating {len(shots)} shots for project '{project}' ...")

    with progressbar(shots, label="Creating shots") as bar:
        for shot in bar:
            try:
                setup_single_shot(project, shot, template)
            except Exception as exc:
                log.error("shot_creation_failed", shot=shot, error=str(exc))
                typer.secho(f"Failed to create shot {shot}: {exc}", fg=typer.colors.RED)
