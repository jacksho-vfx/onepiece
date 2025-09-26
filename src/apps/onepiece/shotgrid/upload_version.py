"""
CLI command for uploading media to a new version in Shotgrid.
"""

from pathlib import Path
import typer
import structlog

from src.libraries.shotgrid.api import ShotGridClient
from src.libraries.shotgrid.models import VersionData

log = structlog.get_logger(__name__)
app = typer.Typer(help="ShotGrid related commands")


@app.command("upload-version")
def upload(
    project_name: str = typer.Option(
        ..., "--project", "-p", help="Name of the ShotGrid project"
    ),
    shot_name: str = typer.Option(..., "--shot", "-s", help="Shot code or name"),
    file_path: Path = typer.Option(
        ..., "--file", "-f", exists=True, file_okay=True, help="File to upload"
    ),
) -> None:
    """
    Upload a file as a new Version to ShotGrid under a project/shot.
    """
    sg_client = ShotGridClient()

    project = sg_client.get_project(project_name)
    if not project:
        typer.echo(f"Project '{project_name}' not found.", err=True)
        raise typer.Exit(code=1)

    shot = sg_client.get_shot(project["code"], shot_name)
    if not shot:
        typer.echo(
            f"Shot '{shot_name}' not found in project '{project_name}'.", err=True
        )
        raise typer.Exit(code=1)

    try:
        version_name = f"{shot_name}_V00)"
        version_data = VersionData(
            entity_type="Version", code=version_name, project_id=project["id"]
        )
        version = sg_client.create_version(version_data)
        typer.echo(
            f"Successfully uploaded version '{version['id']}' for shot '{shot_name}'"
        )
        log.info(
            "upload_version_success",
            project=project_name,
            shot=shot_name,
            file=str(file_path),
        )
    except Exception as e:
        typer.echo(f"Failed to upload version: {e}", err=True)
        log.error(
            "upload_version_fail",
            project=project_name,
            shot=shot_name,
            file=str(file_path),
            error=str(e),
        )
        raise typer.Exit(code=1)
