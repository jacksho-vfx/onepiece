"""CLI: Create a 'version zero' MOV proxy for each shot and upload to ShotGrid."""

from pathlib import Path

from upath import UPath
import structlog
import typer

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.handlers.filepath_handler import FilepathHandler
from libraries.media.transformations import create_1080p_proxy_from_exrs
from libraries.shotgrid.api import ShotGridClient
from libraries.shotgrid.models import (
    PipelineStep,
    TaskCode,
    TaskData,
    VersionData,
)
from libraries.validations.csv_validations import validate_shots_csv
from apps.onepiece.utils.progress import progress_tracker

log = structlog.get_logger(__name__)
app = typer.Typer(help="Shotgrid related commands.")


@app.command(name="version-zero", no_args_is_help=True)
def version_zero(
    csv_file: Path = typer.Argument(..., help="CSV file with shot names."),
    project_name: str = typer.Option(
        ..., "--project-name", "-p", help="ShotGrid project name."
    ),
    fps: int = typer.Option(24, help="Frames per second for MOV output."),
) -> None:
    """
    Create a 'version zero' MOV proxy for each shot and upload to ShotGrid.
    """
    csv_path = UPath(csv_file)
    shot_names = validate_shots_csv(csv_path)
    log.info("starting_version_zero", shots=len(shot_names), project=project_name)

    handler = FilepathHandler()
    sg = ShotGridClient.from_env()

    project_id = sg.get_project_id_by_name(project_name)

    if not project_id:
        raise OnePieceValidationError(
            f"Project '{project_name}' not found. Verify the project name and try again."
        )

    total_shots = len(shot_names)
    successes = 0

    with progress_tracker(
        "Version Zero Generation",
        total=max(total_shots, 1),
        task_description="Processing shots",
    ) as progress:
        for shot_name in shot_names:
            status_message = "Skipped"
            log.info("processing_shot", shot=shot_name)

            try:
                episode, scene, shot = shot_name.split("_")
            except ValueError:
                status_message = "Invalid name"
                log.warning("invalid_shot_name", shot=shot_name)
                progress.advance(description=f"{status_message} {shot_name}")
                continue

            exr_dir = handler.get_shot_dir(project_name, episode, scene, shot) / "exr"
            if not exr_dir.exists():
                status_message = "Missing EXRs"
                log.warning("exr_directory_missing", path=str(exr_dir))
                progress.advance(description=f"{status_message} {shot_name}")
                continue

            proxy_path = exr_dir / f"{shot_name}_proxy.mov"
            try:
                create_1080p_proxy_from_exrs(exr_dir, proxy_path, fps=fps)
            except Exception as e:  # noqa: BLE001 - surfaced to log only.
                status_message = "Proxy failed"
                log.error("proxy_creation_failed", shot=shot_name, error=str(e))
                progress.advance(description=f"{status_message} {shot_name}")
                continue

            shot_entity = sg.get_shot(project_id=project_id, shot_name=shot_name)
            if not shot_entity:
                status_message = "Shot missing"
                log.warning("shot_not_found_in_sg", shot=shot_name)
                progress.advance(description=f"{status_message} {shot_name}")
                continue

            task = sg.get_task(shot_entity["id"], task_name=TaskCode.SHOT_PROXY)
            if not task:
                task_data = TaskData(
                    code=TaskCode.SHOT_PROXY,
                    project_id=project_id,
                    entity_id=shot_entity["id"],
                    related_entity_type=shot_entity["related_entity_type"],
                )
                sg.create_task(
                    data=task_data,
                    step=PipelineStep.COMP,
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
            status_message = "Uploaded"
            successes += 1
            progress.advance(description=f"{status_message} {shot_name}")

        progress.succeed(f"Uploaded {successes} of {total_shots} shots to ShotGrid.")

    log.info("version_zero_complete", project=project_name)
