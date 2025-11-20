"""Validation helpers for Houdini packages."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

__all__ = ["validate_package"]


def _find_hip_files(package_dir: Path) -> tuple[Path, ...]:
    """Return Houdini scene files contained within ``package_dir``."""

    hip_exts = (".hip", ".hiplc", ".hipnc")
    hip_files: list[Path] = []
    for ext in hip_exts:
        hip_files.extend(package_dir.rglob(f"*{ext}"))
    return tuple(sorted({path for path in hip_files if path.is_file()}))


def _paths_in_directory(directory: Path) -> tuple[Path, ...]:
    """Return files within ``directory`` when it exists."""

    if not directory.exists():
        return ()
    return tuple(sorted(path for path in directory.rglob("*") if path.is_file()))


def _find_named_file(package_dir: Path, name: str) -> tuple[Path, ...]:
    """Return files named ``name`` located anywhere in ``package_dir``."""

    return tuple(sorted(path for path in package_dir.rglob(name) if path.is_file()))


def validate_package(package_dir: Path) -> tuple[str, ...]:
    """Return validation issues detected for a Houdini package.

    The validator ensures the packaged payload contains a Houdini scene file,
    rendered outputs, cache data, and a package descriptor before publishing.
    """

    issues: list[str] = []

    hip_files = _find_hip_files(package_dir)
    if not hip_files:
        issues.append(
            "Houdini package must include a .hip, .hiplc, or .hipnc scene file."
        )

    render_files = _paths_in_directory(package_dir / "renders")
    if not render_files:
        issues.append("Houdini package is missing render outputs under renders/.")

    cache_files: Iterable[Path] = (
        file_path
        for cache_dir in package_dir.rglob("caches")
        for file_path in _paths_in_directory(cache_dir)
    )
    if not any(cache_files):
        issues.append("Houdini package must include caches/ data.")

    descriptor_files = _find_named_file(package_dir, "onepiece.json")
    if not descriptor_files:
        issues.append("Houdini package must include a OnePiece package descriptor.")

    metadata_path = package_dir / "metadata.json"
    if not metadata_path.exists():
        issues.append("Houdini package metadata.json is missing.")

    return tuple(issues)
