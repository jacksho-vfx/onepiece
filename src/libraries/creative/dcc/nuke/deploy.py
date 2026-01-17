"""Deployment helpers for the OnePiece Nuke integration."""

from __future__ import annotations

from pathlib import Path

import structlog

from ..deploy_utils import (
    copy_scripts_to as _copy_scripts_to,
    deploy_resources,
    list_script_files,
)

log = structlog.get_logger(__name__)

RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"
DEFAULT_DEPLOY_PATH = Path.home() / ".nuke" / "onepiece"


def get_resource_root() -> Path:
    """Return the root folder containing the packaged Nuke payload."""

    return RESOURCE_ROOT


def get_script_library_path() -> Path:
    """Return the location of bundled Nuke scripts."""

    return RESOURCE_ROOT / "scripts"


def available_script_files(script_directory: Path | None = None) -> list[Path]:
    """List bundled script files sorted for predictable menus."""

    return list_script_files(
        script_directory,
        default_directory=get_script_library_path(),
        predicate=lambda path: path.suffix == ".py",
    )


def deploy_nuke_resources(
    target: Path | str = DEFAULT_DEPLOY_PATH, *, overwrite: bool = False
) -> Path:
    """Copy the packaged Nuke menu and scripts into *target*.

    The target directory is created if missing. If it already exists and
    ``overwrite`` is False, a :class:`FileExistsError` is raised.
    """

    return deploy_resources(
        resource_root=get_resource_root(),
        target=target,
        overwrite=overwrite,
        log=log,
        start_event="nuke.deploy.start",
        complete_event="nuke.deploy.completed",
    )


copy_scripts_to = _copy_scripts_to

__all__ = [
    "available_script_files",
    "copy_scripts_to",
    "DEFAULT_DEPLOY_PATH",
    "deploy_nuke_resources",
    "get_resource_root",
    "get_script_library_path",
]
