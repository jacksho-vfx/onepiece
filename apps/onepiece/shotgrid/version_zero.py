"""
CLI: Create a 'version zero' MOV proxy for each shot and upload to ShotGrid.

Usage:
    onepiece shotgrid version-zero shots.csv --project CoolShow
"""

import UPath
from typing import Optional
import structlog
import typer

from onepiece.libraries.handlers.filepath_handler import LocalFilepathHandler
from onepiece.libraries.media.transformations import create_1080p_proxy_from_exrs
from onepiece.libraries.shotgrid.api import ShotGridClient
from onepiece.libraries.shotgrid.models import VersionData
from onepiece.libraries.validations.csv_validations import validate_shots_csv

log = structlog.get_logger(__name__)
app = typer.Typer(help="Create version-zero proxies and upload to ShotGrid.")


@app.command(name="version-zero", no_args_is_help=True)
def version_zero(
    csv_file: UPath = typer.Argument(..., help="CSV file with shot names."),
    project: str = typer.Option(..., "--project", "-p", help="ShotGrid project name."),
    media_root: Optional[UPath] = typer.Option(
        None, "--media-root", help="Root directory for media files."
    ),
    fps: int = typer.Option(24, help="Frames per second for MOV output."),
):
    """
    For each shot in the CSV:
    1. Find the EXR sequence via the filepath handler.
    2. Create a 1080p MOV proxy.
    3. Upload as Version zero (<shot>_V000) under the task 'Shot Proxy'.
    """
    shot_names = validate_shots_csv(csv_file)
    log.info("starting_version_zero", shots=len(shot_names), project=project)

    handler = LocalFilepathHandler(root=media_root)
    sg = ShotGridClient.from_env()

    for shot_name in shot_names:
        log.info("processing_shot", shot=shot_name)

        try:
            episode, scene, shot = shot_name.split("_")
        except ValueError:
            log.warning("invalid_shot_name", shot=shot_name)
            continue

        exr_dir = handler.get_shot_dir(project, episode, scene, shot) / "exr"
        if not exr_dir.exists():
            log.warning("exr_directory_missing", path=str(exr_dir))
            continue

        proxy_path = exr_dir / f"{shot_name}_proxy.mov"
        try:
            create_1080p_proxy_from_exrs(exr_dir, proxy_path, fps=fps)
        except Exception as e:
            log.error("proxy_creation_failed", shot=shot_name, error=str(e))
            continue

        shot_entity = sg.get_shot(project_name=project, shot_name=shot_name)
        if not shot_entity:
            log.warning("shot_not_found_in_sg", shot=shot_name)
            continue

        task = sg.get_task(shot_entity["id"], task_name="Shot Proxy")
        if not task:
            task = sg.create_task(
                project_name=project,
                entity_type="Shot",
                entity_id=shot_entity["id"],
                name="Shot Proxy",
                step_name="Comp",
            )

        version_code = f"{shot_name}_V000"
        log.info("uploading_version", version=version_code, mov=str(proxy_path))

        version_data = VersionData(
            code=version_code,
            project={"type": "Project", "id": sg.get_project_id_by_name(project)},
            entity={"type": "Shot", "id": shot_entity["id"]},
            sg_task={"type": "Task", "id": task["id"]},
        )
        sg.create_version_with_media(version_data, media_path=proxy_path)

    log.info("version_zero_complete", project=project)
