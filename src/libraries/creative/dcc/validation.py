"""Helpers for validating packaged DCC scenes."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from libraries.creative.dcc.maya.unreal_export_checker import (
    UnrealExportIssue,
    UnrealExportReport,
)

from .models import JSONValue

log = logging.getLogger(__name__)


def _load_package_metadata(package_dir: Path) -> Mapping[str, JSONValue] | None:
    """Return the metadata stored with the packaged scene when available."""

    metadata_path = package_dir / "metadata.json"
    try:
        data = json.loads(metadata_path.read_text())
    except FileNotFoundError:
        log.debug(
            "Maya validation skipped; metadata.json missing",
            extra={"package": str(package_dir)},
        )
        return None
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        log.warning(
            "Maya validation skipped; metadata.json unreadable",
            extra={"package": str(package_dir), "error": str(exc)},
        )
        return None

    if not isinstance(data, Mapping):
        log.warning(
            "Maya validation skipped; metadata.json not an object",
            extra={"package": str(package_dir)},
        )
        return None

    return data


def _normalise_sequence(value: Any) -> tuple[str, ...] | None:
    """Return *value* coerced to a tuple of strings when appropriate."""

    if isinstance(value, (str, bytes)):
        return (str(value),)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return None


def _load_skeleton_summary(
    skeleton_entry: JSONValue,
    package_dir: Path,
) -> tuple[str, tuple[str, ...]] | None:
    """Return skeleton root and joints extracted from ``skeleton_entry``."""

    skeleton_data: Mapping[str, JSONValue] | None
    if isinstance(skeleton_entry, Mapping):
        skeleton_data = skeleton_entry
    elif isinstance(skeleton_entry, str):
        skeleton_path = package_dir / skeleton_entry
        try:
            payload = json.loads(skeleton_path.read_text())
        except FileNotFoundError:
            log.warning(
                "Maya validation skipped; skeleton summary missing",
                extra={"package": str(package_dir), "path": skeleton_path.name},
            )
            return None
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            log.warning(
                "Maya validation skipped; skeleton summary unreadable",
                extra={
                    "package": str(package_dir),
                    "path": skeleton_path.name,
                    "error": str(exc),
                },
            )
            return None
        if not isinstance(payload, Mapping):
            log.warning(
                "Maya validation skipped; skeleton summary not an object",
                extra={"package": str(package_dir), "path": skeleton_path.name},
            )
            return None
        skeleton_data = payload
    else:
        return None

    root = skeleton_data.get("root")
    joints = skeleton_data.get("joints")
    if not isinstance(root, str):
        log.warning(
            "Maya validation skipped; skeleton root invalid",
            extra={"package": str(package_dir)},
        )
        return None

    normalised_joints = _normalise_sequence(joints)
    if not normalised_joints:
        log.warning(
            "Maya validation skipped; skeleton joints invalid",
            extra={"package": str(package_dir)},
        )
        return None

    return root, normalised_joints


def _gather_maya_validation_kwargs(package_dir: Path) -> dict[str, Any] | None:
    """Return keyword arguments for :func:`validate_unreal_export` when available."""

    metadata = _load_package_metadata(package_dir)
    if metadata is None:
        return None

    maya_data = metadata.get("maya")
    if not isinstance(maya_data, Mapping):
        return None

    unreal_data = maya_data.get("unreal_export")
    if not isinstance(unreal_data, Mapping):
        return None

    asset_name = unreal_data.get("asset_name")
    if not isinstance(asset_name, str):
        log.warning(
            "Maya validation skipped; asset name missing",
            extra={"package": str(package_dir)},
        )
        return None

    scale_value = unreal_data.get("scale")
    try:
        scale = float(scale_value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        log.warning(
            "Maya validation skipped; scale invalid",
            extra={"package": str(package_dir)},
        )
        return None

    skeleton_entry = unreal_data.get("skeleton_summary")
    skeleton = _load_skeleton_summary(skeleton_entry, package_dir)
    if skeleton is None:
        return None
    skeleton_root, joints = skeleton

    kwargs: dict[str, Any] = {
        "asset_name": asset_name,
        "scale": scale,
        "skeleton_root": skeleton_root,
        "joints": joints,
    }

    optional_fields = (
        "expected_scale",
        "scale_tolerance",
        "allowed_name_prefixes",
        "required_joints",
        "expected_root",
    )
    for field in optional_fields:
        if field not in unreal_data:
            continue
        value = unreal_data[field]
        if field in {"allowed_name_prefixes", "required_joints"}:
            normalised = _normalise_sequence(value)
            if normalised is not None:
                kwargs[field] = normalised
        else:
            kwargs[field] = value

    return kwargs


def _format_unreal_export_error(report: UnrealExportReport) -> str:
    """Return an error message describing ``report`` issues."""

    errors = [
        f"{issue.code}: {issue.message}"
        for issue in report.issues
        if isinstance(issue, UnrealExportIssue) and issue.severity == "error"
    ]
    if not errors:
        return "Maya Unreal export validation failed with unresolved issues."
    problems = "; ".join(errors)
    return f"Maya Unreal export validation failed; {problems}"


__all__ = [
    "_load_package_metadata",
    "_normalise_sequence",
    "_load_skeleton_summary",
    "_gather_maya_validation_kwargs",
    "_format_unreal_export_error",
]
