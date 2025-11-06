"""Validation helpers for packaged Cinema 4D scenes."""

from __future__ import annotations

import posixpath
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


def _normalise_reference(entry: str) -> str | None:
    """Return ``entry`` stripped, normalised, and using forward slashes."""

    raw = entry.strip()
    if not raw:
        return None
    cleaned = raw.replace("\\", "/")
    normalised = posixpath.normpath(cleaned)
    return normalised


def _looks_like_windows_absolute(path: str) -> bool:
    """Return ``True`` when ``path`` matches a Windows absolute path pattern."""

    if len(path) >= 2 and path[1] == ":" and path[0].isalpha():
        return True
    if path.startswith("//"):
        return True
    return False


def _classify_references(
    package_dir: Path, value: Any
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return valid references and validation issues extracted from ``value``."""

    seen: dict[str, None] = {}
    issues: list[str] = []
    package_root = package_dir.resolve()

    for entry in _iter_reference_paths(value):
        normalised = _normalise_reference(entry)
        if normalised is None:
            continue
        if normalised in seen:
            continue

        reference_path = Path(normalised)
        if reference_path.is_absolute() or _looks_like_windows_absolute(normalised):
            issues.append(
                f"Cinema4D references must be relative to the package: {entry}"
            )
            continue

        candidate = (package_root / reference_path).resolve(strict=False)
        try:
            candidate.relative_to(package_root)
        except ValueError:
            issues.append(f"Cinema4D references must stay within the package: {entry}")
            continue

        seen[normalised] = None

    return tuple(seen.keys()), tuple(issues)


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

    textures, texture_issues = _classify_references(
        package_dir, cinema4d_metadata.get("textures")
    )
    issues.extend(texture_issues)
    missing_textures = _collect_missing_assets(package_dir, textures)
    if missing_textures:
        formatted = ", ".join(sorted(missing_textures))
        issues.append(f"Missing Cinema4D texture files: {formatted}")

    presets, preset_issues = _classify_references(
        package_dir, cinema4d_metadata.get("presets")
    )
    issues.extend(preset_issues)
    missing_presets = _collect_missing_assets(package_dir, presets)
    if missing_presets:
        formatted = ", ".join(sorted(missing_presets))
        issues.append(f"Missing Cinema4D preset files: {formatted}")

    return issues
