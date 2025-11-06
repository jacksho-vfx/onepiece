"""Gather Cinema 4D package dependencies."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from libraries.creative.dcc.validation import _load_package_metadata

from .validation import _classify_references

__all__ = ["GatherResult", "gather_references"]


@dataclass(frozen=True)
class GatherResult:
    """Result describing gathered Cinema 4D assets."""

    copied: tuple[str, ...]
    missing: tuple[str, ...]
    issues: tuple[str, ...]


def _ensure_parent_directory(path: Path) -> None:
    """Create ``path`` parent directories when missing."""

    path.parent.mkdir(parents=True, exist_ok=True)


def _copy_reference(
    reference: str,
    *,
    package_dir: Path,
    source_root: Path | None,
    copied: list[str],
    copied_seen: set[str],
    missing: list[str],
    missing_seen: set[str],
) -> None:
    """Copy ``reference`` into ``package_dir`` when possible."""

    destination = package_dir / Path(reference)
    if destination.exists():
        return

    if source_root is None:
        if reference not in missing_seen:
            missing_seen.add(reference)
            missing.append(reference)
        return

    source = source_root / Path(reference)
    if not source.exists():
        if reference not in missing_seen:
            missing_seen.add(reference)
            missing.append(reference)
        return

    _ensure_parent_directory(destination)
    shutil.copy2(source, destination)
    if reference not in copied_seen:
        copied_seen.add(reference)
        copied.append(reference)


def _gather_from_entries(
    entries: Iterable[str],
    *,
    package_dir: Path,
    source_root: Path | None,
    copied: list[str],
    copied_seen: set[str],
    missing: list[str],
    missing_seen: set[str],
) -> None:
    for reference in entries:
        _copy_reference(
            reference,
            package_dir=package_dir,
            source_root=source_root,
            copied=copied,
            copied_seen=copied_seen,
            missing=missing,
            missing_seen=missing_seen,
        )


def gather_references(
    package_dir: Path, *, source_root: Path | None = None
) -> GatherResult:
    """Collect referenced Cinema 4D assets into ``package_dir``.

    The function reads the package ``metadata.json`` using
    :func:`libraries.creative.dcc.validation._load_package_metadata`, resolves
    texture and preset references, copies missing files from ``source_root``
    when provided, and reports the gathered assets alongside any outstanding
    issues.
    """

    metadata = _load_package_metadata(package_dir)
    if metadata is None:
        return GatherResult((), (), ())

    cinema4d_data = metadata.get("cinema4d")
    if not isinstance(cinema4d_data, dict):
        return GatherResult((), (), ())

    copied: list[str] = []
    missing: list[str] = []
    issues: list[str] = []
    copied_seen: set[str] = set()
    missing_seen: set[str] = set()

    for key in ("textures", "presets"):
        references, reference_issues = _classify_references(
            package_dir, cinema4d_data.get(key)
        )
        issues.extend(reference_issues)
        _gather_from_entries(
            references,
            package_dir=package_dir,
            source_root=source_root,
            copied=copied,
            copied_seen=copied_seen,
            missing=missing,
            missing_seen=missing_seen,
        )

    return GatherResult(tuple(copied), tuple(missing), tuple(issues))
