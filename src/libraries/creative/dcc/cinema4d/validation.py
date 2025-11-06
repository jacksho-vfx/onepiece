"""Validation helpers for packaged Cinema 4D scenes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from libraries.creative.dcc.validation import _load_package_metadata

__all__ = ["validate_package"]


def _iter_reference_paths(value: Any) -> Iterable[str]:
    """Yield string paths contained within ``value``."""

    if isinstance(value, (str, bytes)):
        yield str(value)
        return

    if isinstance(value, Mapping):
        candidate = value.get("path")
        if isinstance(candidate, (str, bytes)):
            yield str(candidate)
        nested = value.get("paths")
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
            for item in nested:
                yield from _iter_reference_paths(item)
        return

    if isinstance(value, Sequence):
        for item in value:
            yield from _iter_reference_paths(item)


def _normalise_references(value: Any) -> tuple[str, ...]:
    """Return the deduplicated reference paths extracted from ``value``."""

    seen: dict[str, None] = {}
    for entry in _iter_reference_paths(value):
        path = entry.strip()
        if not path:
            continue
        seen.setdefault(path)
    return tuple(seen.keys())


def _collect_missing_assets(
    package_dir: Path, entries: Sequence[str]
) -> tuple[str, ...]:
    """Return missing assets for the provided relative ``entries``."""

    missing: list[str] = []
    for relative in entries:
        candidate = package_dir / Path(relative)
        if not candidate.exists():
            missing.append(relative)
    return tuple(missing)


def validate_package(package_dir: Path) -> list[str]:
    """Return validation issues detected for a packaged Cinema 4D scene."""

    metadata = _load_package_metadata(package_dir)
    if metadata is None:
        return []

    cinema4d_metadata = metadata.get("cinema4d")
    if not isinstance(cinema4d_metadata, Mapping):
        return []

    issues: list[str] = []

    textures = _normalise_references(cinema4d_metadata.get("textures"))
    missing_textures = _collect_missing_assets(package_dir, textures)
    if missing_textures:
        formatted = ", ".join(sorted(missing_textures))
        issues.append(f"Missing Cinema4D texture files: {formatted}")

    presets = _normalise_references(cinema4d_metadata.get("presets"))
    missing_presets = _collect_missing_assets(package_dir, presets)
    if missing_presets:
        formatted = ", ".join(sorted(missing_presets))
        issues.append(f"Missing Cinema4D preset files: {formatted}")

    return issues
