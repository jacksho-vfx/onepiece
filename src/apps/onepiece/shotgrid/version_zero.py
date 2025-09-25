"""
CLI: Create a 'version zero' MOV proxy for each shot and upload to ShotGrid.

Usage:
    libraries shotgrid version-zero shots.csv --project CoolShow
"""

import UPath
import structlog
import typer

from src.libraries.handlers.filepath_handler import FilepathHandler
from src.libraries.media.transformations import create_1080p_proxy_from_exrs
from src.libraries.shotgrid.api import ShotGridClient
from src.libraries.shotgrid.models import VersionData
from src.libraries.validations.csv_validations import validate_shots_csv

log = structlog.get_logger(__name__)
app = typer.Typer(help="Create version-zero proxies and upload to ShotGrid.")


@app.command(name="version-zero", no_args_is_help=True)
def version_zero(
    csv_file: UPath = typer.Argument(..., help="CSV file with shot names."),
    project_name: str = typer.Option(
        ..., "--project-name", "-p", help="ShotGrid project name."
    ),
    fps: int = typer.Option(24, help="Frames per second for MOV output."),
) -> None:
    """
    For each shot in the CSV:
    1. Find the EXR sequence via the filepath handler.
    2. Create a 1080p MOV proxy.
    3. Upload as Version zero (<shot>_V000) under the task 'Shot Proxy'.
    """
    shot_names = validate_shots_csv(csv_file)
    log.info("starting_version_zero", shots=len(shot_names), project=project_name)

    handler = FilepathHandler()
    sg = ShotGridClient.from_env()

    project_id = sg.get_project_id_by_name(project_name)

    if not project_id:
        log.error("No project found.", project=project_name)
        return

    for shot_name in shot_names:
        log.info("processing_shot", shot=shot_name)

        try:
            episode, scene, shot = shot_name.split("_")
        except ValueError:
            log.warning("invalid_shot_name", shot=shot_name)
            continue

        exr_dir = handler.get_shot_dir(project_name, episode, scene, shot) / "exr"
        if not exr_dir.exists():
            log.warning("exr_directory_missing", path=str(exr_dir))
            continue

        proxy_path = exr_dir / f"{shot_name}_proxy.mov"
        try:
            create_1080p_proxy_from_exrs(exr_dir, proxy_path, fps=fps)
        except Exception as e:
            log.error("proxy_creation_failed", shot=shot_name, error=str(e))
            continue

        shot_entity = sg.get_shot(project_id=project_id, shot_name=shot_name)
        if not shot_entity:
            log.warning("shot_not_found_in_sg", shot=shot_name)
            continue

        task = sg.get_task(shot_entity["id"], task_name="Shot Proxy")
        if not task:
            sg.create_task(
                project_name=project_name,
                entity_type="Shot",
                entity_id=shot_entity["id"],
                name="Shot Proxy",
                step_name="Comp",
            )

        version_code = f"{shot_name}_V000"
        log.info("uploading_version", version=version_code, mov=str(proxy_path))

        version_data = VersionData(
            entity_type="Version",
            code=version_code,
            description=None,
            project_id=project_id,
        )
        sg.create_version_with_media(version_data, media_path=proxy_path)

    log.info("version_zero_complete", project=project_name)
