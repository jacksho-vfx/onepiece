"""Pre-export validation helpers for Maya to Unreal Engine assets.

The validation rules focus on the most common pitfalls we encounter when
exporting skeletal meshes from Maya to Unreal:

* Scene scale drifting away from the expected centimeter based export unit.
* Skeleton hierarchies missing critical joints that Unreal requires.
* Asset names that do not follow the Unreal naming convention for skeletal
  meshes which later break automation in the engine.

Keeping the checks in pure Python (without importing Maya) lets us unit test the
logic and run validations in lightweight CI environments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# Unreal defaults use centimeters with a scale of 1.0 in Maya.
DEFAULT_EXPECTED_SCALE = 1.0
DEFAULT_SCALE_TOLERANCE = 0.01

# Typical prefixes for skeletal meshes when exporting to Unreal.
DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = ("SK_", "SKEL_")

# Minimal joint set a skeleton must provide for animation retargeting to work.
DEFAULT_REQUIRED_JOINTS: tuple[str, ...] = ("root", "pelvis", "spine_01")
DEFAULT_EXPECTED_ROOT = "root"


@dataclass(frozen=True)
class UnrealExportIssue:
    """Represents a single problem detected during validation."""

    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class UnrealExportReport:
    """Aggregated results for a Maya to Unreal export validation run."""

    asset_name: str
    scale_valid: bool
    skeleton_valid: bool
    naming_valid: bool
    issues: tuple[UnrealExportIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when the validation finished without errors."""

        return not any(issue.severity == "error" for issue in self.issues)


def _check_scale(
    scale: float,
    *,
    expected_scale: float = DEFAULT_EXPECTED_SCALE,
    tolerance: float = DEFAULT_SCALE_TOLERANCE,
) -> tuple[bool, list[UnrealExportIssue]]:
    """Return whether ``scale`` is within ``tolerance`` of ``expected_scale``."""

    issues: list[UnrealExportIssue] = []

    if scale <= 0:
        issues.append(
            UnrealExportIssue(
                code="SCALE_NON_POSITIVE",
                message=("Scene scale must be greater than zero to export to Unreal"),
            )
        )
        return False, issues

    difference = abs(scale - expected_scale)
    if difference > tolerance:
        issues.append(
            UnrealExportIssue(
                code="SCALE_MISMATCH",
                message=(
                    "Scene scale is {:.3f} but Unreal expects {:.3f} (tolerance ±{:.3f})"
                ).format(scale, expected_scale, tolerance),
            )
        )
        return False, issues

    return True, issues


def _check_naming(
    asset_name: str,
    *,
    allowed_prefixes: Sequence[str] = DEFAULT_ALLOWED_PREFIXES,
) -> tuple[bool, list[UnrealExportIssue]]:
    """Return whether ``asset_name`` matches Unreal naming expectations."""

    issues: list[UnrealExportIssue] = []

    stripped = asset_name.strip()
    if stripped != asset_name:
        issues.append(
            UnrealExportIssue(
                code="NAME_WHITESPACE",
                message="Asset names cannot contain leading or trailing whitespace.",
            )
        )

    if " " in asset_name:
        issues.append(
            UnrealExportIssue(
                code="NAME_CONTAINS_SPACES",
                message="Asset names cannot contain spaces when exported to Unreal.",
            )
        )

    if not any(asset_name.startswith(prefix) for prefix in allowed_prefixes):
        formatted = ", ".join(sorted(allowed_prefixes)) or "<none>"
        issues.append(
            UnrealExportIssue(
                code="NAME_PREFIX_INVALID",
                message=(
                    f"Asset name '{asset_name}' must start with one of: {formatted}."
                ),
            )
        )

    return not issues, issues


def _check_skeleton(
    skeleton_root: str,
    joints: Iterable[str],
    *,
    expected_root: str = DEFAULT_EXPECTED_ROOT,
    required_joints: Sequence[str] = DEFAULT_REQUIRED_JOINTS,
) -> tuple[bool, list[UnrealExportIssue]]:
    """Return whether the provided skeleton matches Unreal requirements."""

    issues: list[UnrealExportIssue] = []

    if not skeleton_root:
        issues.append(
            UnrealExportIssue(
                code="SKELETON_ROOT_MISSING",
                message="Skeleton root joint is not specified.",
            )
        )
    elif skeleton_root != expected_root:
        issues.append(
            UnrealExportIssue(
                code="SKELETON_ROOT_MISMATCH",
                message=(
                    f"Skeleton root '{skeleton_root}' must be '{expected_root}' for Unreal."
                ),
            )
        )

    joint_set = {joint for joint in joints}
    if not joint_set:
        issues.append(
            UnrealExportIssue(
                code="SKELETON_NO_JOINTS",
                message="Skeleton must contain at least one joint for export.",
            )
        )
    else:
        missing = sorted(joint for joint in required_joints if joint not in joint_set)
        if missing:
            missing_str = ", ".join(missing)
            issues.append(
                UnrealExportIssue(
                    code="SKELETON_JOINTS_MISSING",
                    message=(
                        f"Skeleton missing required joints for Unreal export: {missing_str}."
                    ),
                )
            )

    return not issues, issues


def validate_unreal_export(
    *,
    asset_name: str,
    scale: float,
    skeleton_root: str,
    joints: Sequence[str],
    expected_scale: float = DEFAULT_EXPECTED_SCALE,
    scale_tolerance: float = DEFAULT_SCALE_TOLERANCE,
    allowed_name_prefixes: Sequence[str] = DEFAULT_ALLOWED_PREFIXES,
    required_joints: Sequence[str] = DEFAULT_REQUIRED_JOINTS,
    expected_root: str = DEFAULT_EXPECTED_ROOT,
) -> UnrealExportReport:
    """Validate Maya scene data prior to exporting to Unreal Engine.

    Parameters
    ----------
    asset_name:
        Name of the asset that will be exported.
    scale:
        Scene scale factor relative to centimeter units.
    skeleton_root:
        Name of the root joint in the skeleton hierarchy.
    joints:
        Collection of all joint names included in the skeleton.
    expected_scale:
        Desired scene scale. Maya exporting to Unreal expects 1.0 by default.
    scale_tolerance:
        Allowed deviation from ``expected_scale`` before an error is reported.
    allowed_name_prefixes:
        Accepted prefixes for the exported asset name.
    required_joints:
        Minimal set of joints that must exist on the skeleton.
    expected_root:
        Name the skeleton root joint must match.
    """

    scale_valid, scale_issues = _check_scale(
        scale, expected_scale=expected_scale, tolerance=scale_tolerance
    )
    naming_valid, naming_issues = _check_naming(
        asset_name, allowed_prefixes=allowed_name_prefixes
    )
    skeleton_valid, skeleton_issues = _check_skeleton(
        skeleton_root,
        joints,
        expected_root=expected_root,
        required_joints=required_joints,
    )

    issues = tuple(scale_issues + naming_issues + skeleton_issues)
    return UnrealExportReport(
        asset_name=asset_name,
        scale_valid=scale_valid,
        skeleton_valid=skeleton_valid,
        naming_valid=naming_valid,
        issues=issues,
    )


__all__ = [
    "DEFAULT_ALLOWED_PREFIXES",
    "DEFAULT_EXPECTED_ROOT",
    "DEFAULT_EXPECTED_SCALE",
    "DEFAULT_REQUIRED_JOINTS",
    "DEFAULT_SCALE_TOLERANCE",
    "UnrealExportIssue",
    "UnrealExportReport",
    "validate_unreal_export",
]
