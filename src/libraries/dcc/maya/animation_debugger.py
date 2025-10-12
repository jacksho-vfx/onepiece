"""Utility helpers for debugging Maya animation scenes.

The logic in this module focuses on quick, lightweight diagnostics that
animators can run before escalating to a technical director.  By keeping the
helpers free of direct Maya imports we can exercise them in unit tests and in
automation environments where Maya is unavailable.  The checks currently cover
three of the most common issues reported by our animation teams:

* Broken constraints that have lost either their driven node or their target.
* Cache links that are missing or reference unloaded simulation caches.
* Invalid frame ranges where the start frame is greater than or equal to the
  end frame.

Each issue surfaces as an :class:`AnimationDebuggerIssue` with a stable error
code and human readable message so downstream tooling can react accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class ConstraintInfo:
    """Description of a Maya constraint used for validation."""

    name: str
    target: str | None
    driven: str | None
    is_enabled: bool = True


@dataclass(frozen=True)
class CacheLinkInfo:
    """Description of a node that should have an associated cache file."""

    node: str
    cache_path: str | None
    is_loaded: bool = True


@dataclass(frozen=True)
class FrameRangeInfo:
    """Representation of an animation segment and its frame range."""

    name: str
    start: float
    end: float


@dataclass(frozen=True)
class AnimationDebuggerIssue:
    """Represents a single problem detected while analysing a scene."""

    code: str
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class AnimationDebuggerReport:
    """Aggregated results for an animation debug pass."""

    scene_name: str
    constraint_issues: tuple[AnimationDebuggerIssue, ...]
    cache_issues: tuple[AnimationDebuggerIssue, ...]
    frame_range_issues: tuple[AnimationDebuggerIssue, ...]

    @property
    def issues(self) -> tuple[AnimationDebuggerIssue, ...]:
        """Return all issues discovered across every check."""

        return self.constraint_issues + self.cache_issues + self.frame_range_issues

    @property
    def has_errors(self) -> bool:
        """Convenience flag for consumers that only care about errors."""

        return any(issue.severity == "error" for issue in self.issues)


def _validate_constraints(
    constraints: Iterable[ConstraintInfo],
) -> list[AnimationDebuggerIssue]:
    """Return issues detected while examining constraint metadata."""

    issues: list[AnimationDebuggerIssue] = []

    for constraint in constraints:
        if not constraint.is_enabled:
            continue

        if not constraint.driven:
            issues.append(
                AnimationDebuggerIssue(
                    code="CONSTRAINT_DRIVEN_MISSING",
                    message=(
                        f"Constraint '{constraint.name}' is missing its driven node; "
                        "animation will no longer follow the expected control."
                    ),
                )
            )

        if not constraint.target:
            issues.append(
                AnimationDebuggerIssue(
                    code="CONSTRAINT_TARGET_MISSING",
                    message=(
                        f"Constraint '{constraint.name}' has no target specified; "
                        "the driven object will not receive animation."
                    ),
                )
            )

    return issues


def _validate_cache_links(
    cache_links: Iterable[CacheLinkInfo],
) -> list[AnimationDebuggerIssue]:
    """Return issues detected while validating simulation cache links."""

    issues: list[AnimationDebuggerIssue] = []

    for cache in cache_links:
        if not cache.cache_path or not cache.cache_path.strip():
            issues.append(
                AnimationDebuggerIssue(
                    code="CACHE_LINK_MISSING",
                    message=(
                        f"Node '{cache.node}' is missing a cache reference; "
                        "playback will not include the expected simulation."
                    ),
                )
            )
            # If there is no cache path we cannot determine the load state.
            continue

        if not cache.is_loaded:
            issues.append(
                AnimationDebuggerIssue(
                    code="CACHE_NOT_LOADED",
                    message=(
                        f"Cache '{cache.cache_path}' for node '{cache.node}' is not loaded; "
                        "ensure the simulation files are accessible."
                    ),
                    severity="warning",
                )
            )

    return issues


def _validate_frame_ranges(
    frame_ranges: Iterable[FrameRangeInfo],
) -> list[AnimationDebuggerIssue]:
    """Return issues detected while validating animation frame ranges."""

    issues: list[AnimationDebuggerIssue] = []

    for frame_range in frame_ranges:
        if frame_range.start >= frame_range.end:
            issues.append(
                AnimationDebuggerIssue(
                    code="FRAME_RANGE_INVALID",
                    message=(
                        f"Frame range '{frame_range.name}' has a start frame ({frame_range.start}) "
                        f"that is greater than or equal to the end frame ({frame_range.end})."
                    ),
                )
            )

    return issues


def debug_animation(
    *,
    scene_name: str,
    constraints: Sequence[ConstraintInfo] | None = None,
    cache_links: Sequence[CacheLinkInfo] | None = None,
    frame_ranges: Sequence[FrameRangeInfo] | None = None,
) -> AnimationDebuggerReport:
    """Run diagnostic checks over the provided animation metadata."""

    constraint_issues = tuple(_validate_constraints(constraints or ()))
    cache_issues = tuple(_validate_cache_links(cache_links or ()))
    frame_range_issues = tuple(_validate_frame_ranges(frame_ranges or ()))

    return AnimationDebuggerReport(
        scene_name=scene_name,
        constraint_issues=constraint_issues,
        cache_issues=cache_issues,
        frame_range_issues=frame_range_issues,
    )
