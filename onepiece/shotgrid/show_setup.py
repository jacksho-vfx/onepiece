"""Minimal helpers for creating ShotGrid project scaffolding."""

from __future__ import annotations

import structlog

from .client import ShotgridClient

log = structlog.get_logger(__name__)


def setup_single_shot(
    project_name: str,
    shot_code: str,
    template: str | None = None,
    client: ShotgridClient | None = None,
) -> dict[str, object]:
    """Ensure that ``project_name`` exists and return metadata for ``shot_code``."""

    if not shot_code:
        raise ValueError("shot_code must be supplied")

    sg_client = client or ShotgridClient()

    project = sg_client.get_or_create_project(project_name)

    log.info(
        "setup_single_shot", project=project_name, shot=shot_code, template=template
    )

    return {"project": project, "shot": {"code": shot_code}}
