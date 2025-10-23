"""
Create a ShotGrid project hierarchy if it does not already exist.

Given:
    * project_name (str)
    * list of shot codes (List[str])

This script will:
    1. Create the Project (optionally using a template) if it doesn't exist.
    2. For each shot code (e.g. "E01_S01_SH010"):
        - Ensure the Episode exists.
        - Ensure the Scene exists.
        - Ensure the Shot exists.

Environment variables for authentication:
    ONEPIECE_SHOTGRID_URL
    ONEPIECE_SHOTGRID_SCRIPT_NAME
    ONEPIECE_SHOTGRID_API_KEY
"""

from __future__ import annotations

import re
from typing import Dict, Any

import structlog

from libraries.integrations.shotgrid.api import ShotGridClient
from libraries.integrations.shotgrid.models import EpisodeData, SceneData, ShotData

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Helper
# --------------------------------------------------------------------------- #
def _parse_shot_code(code: str) -> tuple[str, str, str]:
    """
    Split a shot code into (episode_code, scene_code, shot_code).
    Expects format like E01_S01_SH010 or similar.
    """
    match = re.match(r"(?P<ep>E\d+)[\-_](?P<sc>S\d+)[\-_](?P<sh>SH\d+)", code, re.I)
    if not match:
        raise ValueError(f"Invalid shot code format: {code}")
    return match.group("ep"), match.group("sc"), match.group("sh")


# --------------------------------------------------------------------------- #
# Main Function
# --------------------------------------------------------------------------- #
JSONDict = Dict[str, Any]


def setup_show(
    project_name: str,
    shots: list[str],
    template: str | None = None,
    client: ShotGridClient | None = None,
) -> None:
    """
    Create project, episodes, scenes, and shots in ShotGrid.
    """
    sg_client = client or ShotGridClient()
    project = sg_client.get_or_create_project(project_name, template=template)

    for shot_code in shots:
        episode, scene, shot = _parse_shot_code(shot_code)
        scene_name = "_".join([episode, scene])
        episode_data = EpisodeData(code=episode, project_id=project["id"])
        episode_object: JSONDict = sg_client.get_or_create_episode(episode_data)
        scene_data = SceneData(
            code=scene_name,
            project_id=project["id"],
            episode_id=episode_object["id"],
        )
        scene_object: JSONDict = sg_client.get_or_create_scene(scene_data)
        shot_data = ShotData(
            code=shot_code,
            project_id=project["id"],
            scene_id=scene_object["id"],
        )
        sg_client.get_or_create_shot(shot_data)
        log.info("setup_shot_done", project=project_name, shot=shot_code)


# --------------------------------------------------------------------------- #
# Single Shot Function
# --------------------------------------------------------------------------- #


def setup_single_shot(
    project_name: str,
    shot_code: str,
    client: ShotGridClient | None = None,
) -> None:
    """
    Create or retrieve the full hierarchy for a single shot:
    Project -> Episode -> Scene -> Shot.

    Args:
        project_name: Name of the ShotGrid project
        shot_code: Full shot name, e.g., "ep101_sc01_0010"
        client: ShotGridClient or None

    Returns:
        Dict containing project, episode, scene, shot entities
    """
    log.info("setup_single_shot_start", project=project_name, shot=shot_code)

    sg_client = client or ShotGridClient()

    try:
        parts = shot_code.split("_")
        if len(parts) != 3:
            raise ValueError(
                f"Invalid shot code: {shot_code}, expected ep_sc_shot format"
            )
        episode_code, scene_code, _shot_number = parts
    except Exception as e:
        log.error("shot_code_parse_failed", shot_code=shot_code, error=str(e))
        raise

    project = sg_client.get_project(project_name)
    if not project:
        message = f"ShotGrid project '{project_name}' was not found"
        log.error("shotgrid_project_missing", project=project_name)
        raise RuntimeError(message)

    project_id = project.get("id")
    if project_id is None:
        message = f"ShotGrid project '{project_name}' is missing an id"
        log.error("shotgrid_project_missing_id", project=project_name)
        raise RuntimeError(message)

    episode_data = EpisodeData(code=episode_code, project_id=project_id)
    episode = sg_client.get_or_create_episode(episode_data)
    scene_data = SceneData(
        code=scene_code, project_id=project_id, episode_id=episode["id"]
    )
    scene = sg_client.get_or_create_scene(scene_data)

    shot_data = ShotData(
        code=shot_code,
        project_id=project_id,
        scene_id=scene["id"],
    )
    sg_client.get_or_create_shot(shot_data)

    log.info("setup_single_shot_complete", project=project_name, shot=shot_code)
