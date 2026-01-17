"""Shared deployment utilities for DCC integrations."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Iterable, Protocol


class Logger(Protocol):
    """Protocol for structured loggers used by DCC deploy helpers."""

    def info(self, event: str, **kwargs: object) -> None:
        """Log an informational event."""


def list_script_files(
    script_directory: Path | None,
    *,
    default_directory: Path,
    predicate: Callable[[Path], bool],
) -> list[Path]:
    """Return script files in *script_directory* filtered by *predicate*."""

    directory = (script_directory or default_directory).resolve()
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if predicate(path))


def deploy_resources(
    *,
    resource_root: Path,
    target: Path | str,
    overwrite: bool,
    log: Logger,
    start_event: str,
    complete_event: str,
    ensure_parent: bool = False,
) -> Path:
    """Copy the packaged DCC resources into *target* and return the path."""

    destination = Path(target).expanduser().resolve()
    if destination.exists():
        if not overwrite:
            raise FileExistsError(
                f"Destination '{destination}' already exists; pass --overwrite to replace it."
            )
        shutil.rmtree(destination)

    if ensure_parent:
        destination.parent.mkdir(parents=True, exist_ok=True)

    log.info(start_event, source=str(resource_root), destination=str(destination))
    shutil.copytree(resource_root, destination)
    log.info(complete_event, destination=str(destination))
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
