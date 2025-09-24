import typer
from typer import progressbar
from pathlib import Path
import structlog

from onepiece.shotgrid.show_setup import setup_single_shot

log = structlog.get_logger(__name__)
app = typer.Typer(help="Show setup commands for ShotGrid.")


@app.command("show-setup")
def show_setup_command(csv: Path, project: str, template: str = typer.Option(None)):
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
