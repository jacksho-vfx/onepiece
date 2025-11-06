"""Validation helpers for packaged Cinema 4D scenes."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from libraries.creative.dcc.validation import _load_package_metadata

__all__ = ["NormaliseResult", "normalise_asset_paths", "validate_package"]


@dataclass(frozen=True)
class NormaliseResult:
    """Result describing Cinema 4D metadata normalisation."""

    metadata: dict[str, Any] | None
    updated: bool
    warnings: tuple[str, ...]


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


def _rebase_reference(
    reference: str, package_root: Path
) -> tuple[str, str | None, bool]:
    """Return ``reference`` rebased relative to ``package_root`` when possible."""

    changed = False

    if _looks_like_windows_absolute(reference):
        package_drive = package_root.drive
        if package_drive:
            package_prefix = package_root.as_posix().lower()
            reference_lower = reference.lower()
            if reference_lower.startswith(package_prefix):
                remainder = reference[len(package_prefix) :].lstrip("/")
                rebased = remainder or "."
                if rebased != reference:
                    changed = True
                return rebased, None, changed
        warning = (
            "Unable to rebase Windows absolute path outside the package: "
            f"{reference}"
        )
        return reference, warning, changed

    path = Path(reference)
    if path.is_absolute():
        try:
            relative = path.relative_to(package_root)
        except ValueError:
            warning = (
                "Unable to rebase absolute path outside the package: " f"{reference}"
            )
            return reference, warning, changed
        rebased = relative.as_posix()
        if rebased != reference:
            changed = True
        return rebased, None, changed

    candidate = (package_root / path).resolve(strict=False)
    try:
        candidate.relative_to(package_root)
    except ValueError:
        warning = (
            "Relative path escapes the package after normalisation: " f"{reference}"
        )
        return reference, warning, changed

    return reference, None, changed


def _normalise_asset_entries(
    package_dir: Path, value: Any
) -> tuple[list[str], tuple[str, ...], bool]:
    """Return normalised asset entries extracted from ``value``."""

    package_root = package_dir.resolve()
    original_entries: list[str] = []
    normalised_entries: list[str] = []
    warnings: list[str] = []
    changed = False

    for entry in _iter_reference_paths(value):
        original_entries.append(entry)
        normalised = _normalise_reference(entry)
        if normalised is None:
            continue
        if normalised != entry:
            changed = True
        rebased, warning, rebased_changed = _rebase_reference(normalised, package_root)
        if warning is not None:
            warnings.append(warning)
        if rebased_changed:
            changed = True
        normalised_entries.append(rebased)

    if not changed:
        processed_original: list[str] = []
        for item in original_entries:
            candidate = _normalise_reference(item)
            if candidate is None:
                continue
            processed_original.append(candidate)
        if processed_original != normalised_entries:
            changed = True

    return normalised_entries, tuple(warnings), changed


def normalise_asset_paths(package_dir: Path) -> NormaliseResult:
    """Return normalised Cinema 4D metadata for ``package_dir``."""

    metadata = _load_package_metadata(package_dir)
    if metadata is None:
        message = "Cinema 4D package metadata.json is missing or unreadable."
        return NormaliseResult(None, False, (message,))

    if not isinstance(metadata, dict):
        message = "Cinema 4D metadata is not a JSON object."
        return NormaliseResult(None, False, (message,))

    cinema4d_data = metadata.get("cinema4d")
    if not isinstance(cinema4d_data, dict):
        message = "Cinema 4D metadata does not contain a 'cinema4d' section."
        return NormaliseResult(None, False, (message,))

    metadata_copy: dict[str, Any] = dict(metadata)
    cinema4d_copy = dict(cinema4d_data)
    metadata_copy["cinema4d"] = cinema4d_copy

    all_warnings: list[str] = []
    updated = False

    for key in ("textures", "presets"):
        if key not in cinema4d_copy:
            continue
        entries, entry_warnings, changed = _normalise_asset_entries(
            package_dir, cinema4d_copy[key]
        )
        all_warnings.extend(entry_warnings)
        if changed:
            cinema4d_copy[key] = entries
            updated = True

    return NormaliseResult(metadata_copy, updated, tuple(all_warnings))


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
