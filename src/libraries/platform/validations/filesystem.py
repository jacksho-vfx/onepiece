"""Filesystem validation helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, TypedDict

__all__ = ["check_paths", "preflight_report"]


def _nearest_existing_parent(path: Path) -> Path:
    """Return the closest ancestor of *path* that exists on disk."""

    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


def _free_space_in_gb(path: Path) -> float:
    """Return the available free space in gigabytes for *path*.

    ``shutil.disk_usage`` expects the path to exist. When the requested path is
    missing we fall back to the nearest existing ancestor so callers querying
    yet-to-be-created directories still receive the correct disk capacity.
    """

    target = _nearest_existing_parent(path)
    try:
        return shutil.disk_usage(target).free / 1e9
    except FileNotFoundError:
        return 0.0


class PathInfo(TypedDict):
    exists: bool
    writable: bool
    free_space_gb: float


def check_paths(paths: Iterable[Path | str]) -> dict[str, PathInfo]:
    """Validate a collection of paths.

    Each entry in ``paths`` is expanded to a :class:`Path` and a dictionary is
    returned describing the state of the path.  The dictionary contains three
    keys: ``exists``, ``writable`` and ``free_space_gb``.
    """

    results: dict[str, PathInfo] = {}
    for raw_path in paths:
        if isinstance(raw_path, Path):
            raw_string = os.fspath(raw_path)
        else:
            raw_string = str(raw_path)

        expanded = os.path.expanduser(os.path.expandvars(raw_string))
        path = Path(expanded).resolve(strict=False)
        exists = path.exists()
        access_target = path if exists else _nearest_existing_parent(path)
        writable = os.access(access_target, os.W_OK)
        free_space = _free_space_in_gb(path)
        results[str(path)] = PathInfo(
            exists=exists,
            writable=bool(writable),
            free_space_gb=free_space,
        )
    return results


def preflight_report(paths: Iterable[Path | str], min_free_gb: float = 1.0) -> bool:
    """Print a human readable pre-flight report for *paths*.

    The function returns ``True`` when every path exists, is writable and has at
    least ``min_free_gb`` available.  Printing keeps the behaviour observable for
    command line usage without imposing extra requirements on consumers.
    """

    results = check_paths(paths)
    all_ok = True
    for path, info in results.items():
        status = "OK"
        if not info["exists"]:
            status = "MISSING"
        elif not info["writable"]:
            status = "NOT WRITABLE"
        elif info["free_space_gb"] < min_free_gb:
            status = f"LOW SPACE ({info['free_space_gb']:.2f} GB)"

        if status != "OK":
            all_ok = False
        print(f"{path}: {status}")
    return all_ok
