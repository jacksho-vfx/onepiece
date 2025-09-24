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

import re
from typing import Optional

import structlog

from .api import ShotGridClient
from .models import EpisodeData, ProjectData, SceneData, ShotData

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
def setup_show(
    project_name: str,
    shots: list[str],
    template_project_id: int | None = None,
    client: ShotGridClient | None = None,
) -> None:
    """
    Create project, episodes, scenes, and shots in ShotGrid.
    """
    sg_client = client or ShotGridClient()
    project = sg_client.get_or_create_project(project_name)

    for shot_code in shots:
        episode = sg_client.get_or_create_episode(project["id"], "Main")
        _scene = sg_client.get_or_create_scene(project["id"], episode["id"], "Scene01")
        sg_client.get_or_create_shot(project["id"], shot_code)
        log.info("setup_shot_done", project=project_name, shot=shot_code)
        
# --------------------------------------------------------------------------- #
# Single Shot Function
# --------------------------------------------------------------------------- #
        
def setup_single_shot(
    project_name: str,
    shot_code: str,
    template_project_id: Optional[int] = None,
    client: ShotGridClient | None = None,
) -> dict:
    """
    Create or retrieve the full hierarchy for a single shot:
    Project -> Episode -> Scene -> Shot.

    Args:
        project_name: Name of the ShotGrid project
        shot_code: Full shot name, e.g., "ep101_sc01_0010"
        template_project_id: Optional ShotGrid project ID to copy hierarchy from

    Returns:
        Dict containing project, episode, scene, shot entities
    """
    log.info("setup_single_shot_start", project=project_name, shot=shot_code)

    sg_client = client or ShotGridClient()

    try:
        parts = shot_code.split("_")
        if len(parts) != 3:
            raise ValueError(f"Invalid shot code: {shot_code}, expected ep_sc_shot format")
        episode_code, scene_code, _shot_number = parts
    except Exception as e:
        log.error("shot_code_parse_failed", shot_code=shot_code, error=str(e))
        raise

    project_data = ProjectData(name=project_name)
    project = sg_client.get_or_create_project(project_data, template_id=template_project_id)

    episode_data = EpisodeData(name=episode_code, project_id=project["id"])
    episode = sg_client.get_or_create_episode(episode_data)

    scene_data = SceneData(name=scene_code, project_id=project["id"], episode_id=episode["id"])
    scene = sg_client.get_or_create_scene(scene_data)

    shot_data = ShotData(
        code=shot_code,
        project_id=project["id"],
        episode_id=episode["id"],
        scene_id=scene["id"]
    )
    shot = sg_client.get_or_create_shot(shot_data)

    log.info("setup_single_shot_complete", project=project_name, shot=shot_code)
    return {
        "project": project,
        "episode": episode,
        "scene": scene,
        "shot": shot
    }
