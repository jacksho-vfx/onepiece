"""
CLI command for uploading media to a new version in Shotgrid.
"""

from pathlib import Path
import typer
import structlog

from onepiece.shotgrid.client import ShotgridClient


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
    description: str = typer.Option(
        "", "--description", "-d", help="Optional version description"
    ),
    sg_url: str = typer.Option(
        None, "--sg-url", help="ShotGrid URL, defaults to env variable SHOTGRID_URL"
    ),
):
    """
    Upload a file as a new Version to ShotGrid under a project/shot.
    """
    sg_client = ShotgridClient(url=sg_url)

    project = sg_client.get_project_by_name(project_name)
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
        version_data = sg_client.create_version(
            project_id=project["id"],
            entity_id=shot["id"],
            file_path=str(file_path),
            description=description,
        )
        typer.echo(
            f"Successfully uploaded version '{version_data['id']}' for shot '{shot_name}'"
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
