"""Tests for the Maya animation debugger helper utilities."""

from libraries.creative.dcc.maya.animation_debugger import (
    AnimationDebuggerIssue,
    CacheLinkInfo,
    ConstraintInfo,
    FrameRangeInfo,
    debug_animation,
)


def test_debug_animation_reports_common_issues() -> None:
    """The debugger should surface broken constraints and invalid ranges."""

    report = debug_animation(
        scene_name="shot010",
        constraints=[
            ConstraintInfo(name="aimConstraint1", target=None, driven="camera"),
            ConstraintInfo(name="parentConstraint1", target="locator1", driven=None),
            ConstraintInfo(
                name="disabledConstraint",
                target=None,
                driven=None,
                is_enabled=False,
            ),
        ],
        cache_links=[
            CacheLinkInfo(node="simMesh", cache_path=None),
            CacheLinkInfo(node="simMesh2", cache_path="simMesh2.abc", is_loaded=False),
        ],
        frame_ranges=[FrameRangeInfo(name="main", start=120.0, end=100.0)],
    )

    constraint_codes = {issue.code for issue in report.constraint_issues}
    assert constraint_codes == {
        "CONSTRAINT_TARGET_MISSING",
        "CONSTRAINT_DRIVEN_MISSING",
    }

    cache_codes = [issue.code for issue in report.cache_issues]
    assert cache_codes == ["CACHE_LINK_MISSING", "CACHE_NOT_LOADED"]

    frame_range_codes = [issue.code for issue in report.frame_range_issues]
    assert frame_range_codes == ["FRAME_RANGE_INVALID"]

    # Mixing errors and warnings should still mark the report as containing errors.
    assert report.has_errors is True


def test_debug_animation_handles_warning_only_scenarios() -> None:
    """Warnings alone should not flip the ``has_errors`` convenience property."""

    report = debug_animation(
        scene_name="shot020",
        cache_links=[
            CacheLinkInfo(node="simMesh", cache_path="simMesh.abc", is_loaded=False)
        ],
    )

    assert report.cache_issues == (
        AnimationDebuggerIssue(
            code="CACHE_NOT_LOADED",
            message="Cache 'simMesh.abc' for node 'simMesh' is not loaded; ensure the simulation files are accessible.",
            severity="warning",
        ),
    )
    assert report.has_errors is False


def test_debug_animation_returns_clean_report_for_valid_data() -> None:
    """A scene without issues should return an empty report."""

    report = debug_animation(
        scene_name="shot030",
        constraints=[
            ConstraintInfo(name="aimConstraint1", target="locator1", driven="camera"),
        ],
        cache_links=[
            CacheLinkInfo(node="simMesh", cache_path="simMesh.abc", is_loaded=True),
        ],
        frame_ranges=[FrameRangeInfo(name="main", start=100.0, end=150.0)],
    )

    assert report.issues == ()
    assert report.has_errors is False
