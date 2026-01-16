"""Deployment helpers for the OnePiece Unreal integration."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

import structlog

log = structlog.get_logger(__name__)

RESOURCE_ROOT = Path(__file__).resolve().parent / "resources"
DEFAULT_DEPLOY_PATH = Path.home() / "OnePiece" / "Unreal"


def get_resource_root() -> Path:
    """Return the root folder containing the packaged Unreal payload."""

    return RESOURCE_ROOT


def get_script_library_path() -> Path:
    """Return the location of bundled Unreal scripts."""

    return RESOURCE_ROOT / "scripts"


def available_script_files(script_directory: Path | None = None) -> list[Path]:
    """List bundled script files sorted for predictable menus."""

    directory = (script_directory or get_script_library_path()).resolve()
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.suffix == ".py" and not path.name.startswith("__")
    )


def deploy_unreal_resources(
    target: Path | str = DEFAULT_DEPLOY_PATH, *, overwrite: bool = False
) -> Path:
    """Copy the packaged Unreal menu and scripts into *target*.

    The target directory is created if missing. If it already exists and
    ``overwrite`` is False, a :class:`FileExistsError` is raised.
    """

    destination = Path(target).expanduser().resolve()
    source = get_resource_root()

    if destination.exists():
        if not overwrite:
            raise FileExistsError(
                f"Destination '{destination}' already exists; pass --overwrite to replace it."
            )
        shutil.rmtree(destination)

    log.info("unreal.deploy.start", source=str(source), destination=str(destination))
    shutil.copytree(source, destination)
    log.info("unreal.deploy.completed", destination=str(destination))
    return destination


def copy_scripts_to(target: Path, scripts: Iterable[Path]) -> list[Path]:
    """Copy specific script files into *target* and return the new paths."""

    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for script in scripts:
        destination = target / script.name
        destination.write_bytes(script.read_bytes())
        written.append(destination)
    return written


__all__ = [
    "available_script_files",
    "copy_scripts_to",
    "deploy_unreal_resources",
    "get_resource_root",
    "get_script_library_path",
]
