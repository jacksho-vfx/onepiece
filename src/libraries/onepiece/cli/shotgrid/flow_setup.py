import csv
from pathlib import Path

import structlog
import typer

from libraries.integrations.shotgrid.show_setup import setup_single_shot
from apps.onepiece.utils.progress import progress_tracker

log = structlog.get_logger(__name__)
app = typer.Typer(help="Shotgrid related commands.")


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
    total_shots = len(shots)
    typer.echo(f"Creating {total_shots} shots for project '{project}' ...")

    failures = 0
    with progress_tracker(
        "ShotGrid Show Setup",
        total=total_shots,
        task_description="Provisioning shots",
    ) as progress:
        for shot in shots:
            try:
                setup_single_shot(project, shot, template)
                progress.advance(description=f"Created {shot}")
            except Exception as exc:
                failures += 1
                progress.advance(description=f"Failed {shot}")
                log.error("shot_creation_failed", shot=shot, error=str(exc))
                typer.secho(f"Failed to create shot {shot}: {exc}", fg=typer.colors.RED)

        created = total_shots - failures
        if failures:
            progress.succeed(
                f"Created {created} of {total_shots} shots. {failures} failed."
            )
        else:
            progress.succeed(f"Created {total_shots} shots for project '{project}'.")
