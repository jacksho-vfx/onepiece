"""Helpers for provisioning ShotGrid hierarchy entries used in tests."""

from __future__ import annotations

import re
from typing import Any, Iterable, Tuple

import structlog

from libraries.integrations.shotgrid.api import ShotGridClient
from libraries.integrations.shotgrid.models import EpisodeData, SceneData, ShotData

log = structlog.get_logger(__name__)

_SHOT_CODE_PATTERN = re.compile(
    r"(?P<episode>E\d+)[_-](?P<scene>S\d+)[_-](?P<shot>SH\d+)",
    re.IGNORECASE,
)


def _normalise_part(value: str) -> str:
    """Return an upper-case code stripped of surrounding whitespace."""

    return value.strip().upper()


def _parse_shot_code(code: str) -> Tuple[str, str, str]:
    """Split *code* into episode, scene and shot identifiers."""

    match = _SHOT_CODE_PATTERN.fullmatch(code.replace("-", "_").strip())
    if not match:
        raise ValueError(f"Invalid shot code format: {code}")
    episode = _normalise_part(match.group("episode"))
    scene = _normalise_part(match.group("scene"))
    shot = _normalise_part(match.group("shot"))
    return episode, scene, shot


def _entity_id(entity: Any) -> int | None:
    """Return the ``id`` attribute from a ShotGrid entity mapping."""

    if isinstance(entity, dict):
        identifier = entity.get("id")
        if isinstance(identifier, int):
            return identifier
    return None


def setup_show(
    project_name: str,
    shots: Iterable[str],
    template: str | None = None,
    *,
    client: ShotGridClient | None = None,
) -> None:
    """Ensure *shots* exist beneath *project_name* within ShotGrid."""

    sg_client = client or ShotGridClient()
    project = sg_client.get_or_create_project(project_name, template=template)
    project_id = _entity_id(project)
    if project_id is None:
        msg = f"ShotGrid project '{project_name}' could not be created"
        raise RuntimeError(msg)

    for shot_code in shots:
        _setup_single_shot_with_project(
            sg_client,
            project_id=project_id,
            project_name=project_name,
            shot_code=shot_code,
        )


def setup_single_shot(
    project_name: str,
    shot_code: str,
    *,
    client: ShotGridClient | None = None,
) -> None:
    """Create the ShotGrid hierarchy for a single *shot_code*."""

    sg_client = client or ShotGridClient()
    project = sg_client.get_project(project_name)

    if project is None:
        create_project = getattr(sg_client, "get_or_create_project", None)
        if callable(create_project):
            project = create_project(project_name, template=None)
            if project is None:
                msg = f"Project '{project_name}' could not be retrieved or created"
                raise RuntimeError(msg)
        else:
            msg = f"ShotGrid project '{project_name}' was not found"
            raise RuntimeError(msg)

    project_id = _entity_id(project)
    if project_id is None:
        msg = f"ShotGrid project '{project_name}' is missing an id"
        raise RuntimeError(msg)

    _setup_single_shot_with_project(
        sg_client,
        project_id=project_id,
        project_name=project_name,
        shot_code=shot_code,
    )


def _setup_single_shot_with_project(
    sg_client: ShotGridClient,
    *,
    project_id: int,
    project_name: str,
    shot_code: str,
) -> None:
    """Create an episode, scene and shot for *shot_code* in *project_name*."""

    episode_code, scene_code, _ = _parse_shot_code(shot_code)

    log.info(
        "setup_single_shot_start",
        project=project_name,
        shot=shot_code,
        project_id=project_id,
    )

    episode_data = EpisodeData(code=episode_code, project_id=project_id)
    episode = sg_client.get_or_create_episode(episode_data)
    episode_id = _entity_id(episode)

    scene_data = SceneData(
        code=scene_code,
        project_id=project_id,
        episode_id=episode_id,
    )
    scene = sg_client.get_or_create_scene(scene_data)
    scene_id = _entity_id(scene)

    shot_data = ShotData(code=shot_code, project_id=project_id, scene_id=scene_id)
    sg_client.get_or_create_shot(shot_data)

    log.info(
        "setup_single_shot_complete",
        project=project_name,
        shot=shot_code,
        project_id=project_id,
    )


__all__ = ["setup_show", "setup_single_shot"]
