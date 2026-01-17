"""Deployment helpers for the OnePiece Maya integration."""

from __future__ import annotations

from pathlib import Path

import structlog

from ..deploy_utils import (
    copy_scripts_to,
    deploy_resources,
    list_script_files,
)

log = structlog.get_logger(__name__)

RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"
DEFAULT_DEPLOY_PATH = Path.home() / "Documents" / "maya" / "scripts" / "onepiece"
_SCRIPT_EXTENSIONS = {".py"}


def get_resource_root() -> Path:
    """Return the root folder containing the packaged Maya payload."""

    return RESOURCE_ROOT


def get_script_library_path() -> Path:
    """Return the location of bundled Maya scripts."""

    return RESOURCE_ROOT / "scripts"


def available_script_files(script_directory: Path | None = None) -> list[Path]:
    """List bundled script files sorted for predictable menus."""

    return list_script_files(
        script_directory,
        default_directory=get_script_library_path(),
        predicate=lambda path: path.is_file() and path.suffix in _SCRIPT_EXTENSIONS,
    )


def deploy_maya_resources(
    target: Path | str = DEFAULT_DEPLOY_PATH, *, overwrite: bool = False
) -> Path:
    """Copy the packaged Maya panel, menu, and scripts into *target*.

    The target directory is created if missing. If it already exists and
    ``overwrite`` is False, a :class:`FileExistsError` is raised.
    """

    return deploy_resources(
        resource_root=get_resource_root(),
        target=target,
        overwrite=overwrite,
        log=log,
        start_event="maya.deploy.start",
        complete_event="maya.deploy.completed",
        ensure_parent=True,
    )


__all__ = [
    "available_script_files",
    "copy_scripts_to",
    "DEFAULT_DEPLOY_PATH",
    "deploy_maya_resources",
    "get_resource_root",
    "get_script_library_path",
]
