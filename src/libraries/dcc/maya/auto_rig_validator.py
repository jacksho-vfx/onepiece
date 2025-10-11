"""Lightweight rig validation helpers for Maya auto-rig imports.

The helpers in this module provide pure Python validation routines that mirror
common checks performed when bringing character rigs into animation shots.
They focus on three broad categories that typically break downstream work:

* Naming conventions for joints and controls.
* The integrity of critical joint hierarchy relationships.
* Presence of required control attributes that downstream tools rely on.

Keeping the validation logic free of direct Maya dependencies makes it easy to
unit test and to run during automated ingest pipelines where Maya is not
available.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Mapping, MutableMapping, Sequence

# Typical studio defaults for skeleton and control naming.
DEFAULT_JOINT_PREFIXES: tuple[str, ...] = ("JNT_", "SKL_")
DEFAULT_CONTROL_PREFIXES: tuple[str, ...] = ("CTL_", "CTRL_")

# Minimal relationships that confirm the high-level structure of a rig.
DEFAULT_REQUIRED_HIERARCHY: tuple[tuple[str, str], ...] = (
    ("JNT_root", "JNT_spine"),
    ("JNT_spine", "JNT_chest"),
)

# Control channels that animation tooling frequently relies on being present.
DEFAULT_REQUIRED_CONTROL_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "CTL_Main": ("visibility", "rigScale"),
}


@dataclass(frozen=True)
class RigValidationIssue:
    """Represents a single validation issue detected on import."""

    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class RigValidationReport:
    """Aggregated results for an auto-rig validation run."""

    rig_name: str
    naming_valid: bool
    hierarchy_valid: bool
    controls_valid: bool
    issues: tuple[RigValidationIssue, ...]

    @property
    def is_valid(self) -> bool:
        """Return ``True`` when no error level issues were produced."""

        return not any(issue.severity == "error" for issue in self.issues)


def _ensure_prefix(name: str, prefixes: Sequence[str]) -> bool:
    """Return ``True`` if ``name`` starts with one of ``prefixes``."""

    if not prefixes:
        return True
    return any(name.startswith(prefix) for prefix in prefixes)


def _check_for_duplicates(names: Iterable[str], *, kind: str) -> list[RigValidationIssue]:
    """Return issues for any duplicated ``names``."""

    issues: list[RigValidationIssue] = []
    counts = Counter(names)
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        joined = ", ".join(duplicates)
        issues.append(
            RigValidationIssue(
                code=f"{kind.upper()}_DUPLICATE_NAME",
                message=f"Duplicate {kind} names detected: {joined}.",
            )
        )
    return issues


def _check_naming(
    *,
    joint_names: Sequence[str],
    control_names: Sequence[str],
    joint_prefixes: Sequence[str],
    control_prefixes: Sequence[str],
) -> tuple[bool, list[RigValidationIssue]]:
    """Validate joint and control naming conventions."""

    issues: list[RigValidationIssue] = []

    for joint in joint_names:
        if not _ensure_prefix(joint, joint_prefixes):
            formatted = ", ".join(sorted(joint_prefixes)) or "<none>"
            issues.append(
                RigValidationIssue(
                    code="JOINT_BAD_PREFIX",
                    message=f"Joint '{joint}' must start with one of: {formatted}.",
                )
            )

    for control in control_names:
        if not _ensure_prefix(control, control_prefixes):
            formatted = ", ".join(sorted(control_prefixes)) or "<none>"
            issues.append(
                RigValidationIssue(
                    code="CONTROL_BAD_PREFIX",
                    message=f"Control '{control}' must start with one of: {formatted}.",
                )
            )

    issues.extend(_check_for_duplicates(joint_names, kind="joint"))
    issues.extend(_check_for_duplicates(control_names, kind="control"))

    return not issues, issues


def _check_hierarchy(
    *,
    hierarchy_pairs: Iterable[tuple[str, str]],
    required_hierarchy: Sequence[tuple[str, str]],
) -> tuple[bool, list[RigValidationIssue]]:
    """Return whether the required parent/child relationships exist."""

    issues: list[RigValidationIssue] = []
    available = set(hierarchy_pairs)

    for parent, child in required_hierarchy:
        if (parent, child) not in available:
            issues.append(
                RigValidationIssue(
                    code="HIERARCHY_MISSING_RELATIONSHIP",
                    message=(
                        f"Missing required hierarchy link '{parent} -> {child}'."
                    ),
                )
            )

    return not issues, issues


def _check_controls(
    *,
    controls: Mapping[str, Mapping[str, object]],
    required_attributes: Mapping[str, Sequence[str]],
) -> tuple[bool, list[RigValidationIssue]]:
    """Return whether controls expose the expected attribute channels."""

    issues: list[RigValidationIssue] = []

    for control, expected_attributes in required_attributes.items():
        if control not in controls:
            issues.append(
                RigValidationIssue(
                    code="CONTROL_MISSING",
                    message=f"Required control '{control}' was not found in the rig.",
                )
            )
            continue

        available = controls[control]
        for attribute in expected_attributes:
            if attribute not in available:
                issues.append(
                    RigValidationIssue(
                        code="CONTROL_MISSING_ATTRIBUTE",
                        message=(
                            f"Control '{control}' is missing required attribute '{attribute}'."
                        ),
                    )
                )

    return not issues, issues


def _coerce_controls(
    controls: Mapping[str, Mapping[str, object]] | Sequence[str] | None,
) -> tuple[dict[str, MutableMapping[str, object]], tuple[str, ...]]:
    """Return a mapping of control names and the raw list of names provided."""

    if controls is None:
        return {}, ()

    if isinstance(controls, Mapping):
        mapping = {name: dict(attributes) for name, attributes in controls.items()}
        return mapping, tuple(mapping.keys())

    coerced: dict[str, MutableMapping[str, object]] = {}
    names: list[str] = []
    for name in controls:
        names.append(name)
        coerced.setdefault(name, {})
    return coerced, tuple(names)


def validate_rig_import(
    *,
    rig_name: str,
    joints: Sequence[str],
    hierarchy: Iterable[tuple[str, str]],
    controls: Mapping[str, Mapping[str, object]] | Sequence[str] | None,
    allowed_joint_prefixes: Sequence[str] = DEFAULT_JOINT_PREFIXES,
    allowed_control_prefixes: Sequence[str] = DEFAULT_CONTROL_PREFIXES,
    required_hierarchy: Sequence[tuple[str, str]] = DEFAULT_REQUIRED_HIERARCHY,
    required_control_attributes: Mapping[str, Sequence[str]] = DEFAULT_REQUIRED_CONTROL_ATTRIBUTES,
) -> RigValidationReport:
    """Validate a rig on import before allowing it into an animation shot."""

    issues: list[RigValidationIssue] = []

    if not rig_name.strip():
        issues.append(
            RigValidationIssue(
                code="RIG_NAME_EMPTY",
                message="Rig name must be provided when validating an import.",
            )
        )

    control_map, raw_control_names = _coerce_controls(controls)
    control_names = raw_control_names or tuple(control_map.keys())

    naming_valid, naming_issues = _check_naming(
        joint_names=joints,
        control_names=control_names,
        joint_prefixes=allowed_joint_prefixes,
        control_prefixes=allowed_control_prefixes,
    )
    issues.extend(naming_issues)

    hierarchy_valid, hierarchy_issues = _check_hierarchy(
        hierarchy_pairs=hierarchy,
        required_hierarchy=required_hierarchy,
    )
    issues.extend(hierarchy_issues)

    controls_valid, control_issues = _check_controls(
        controls=control_map,
        required_attributes=required_control_attributes,
    )
    issues.extend(control_issues)

    return RigValidationReport(
        rig_name=rig_name,
        naming_valid=naming_valid,
        hierarchy_valid=hierarchy_valid,
        controls_valid=controls_valid,
        issues=tuple(issues),
    )
