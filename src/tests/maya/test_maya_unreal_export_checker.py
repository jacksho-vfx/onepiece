from libraries.dcc.maya import (
    DEFAULT_ALLOWED_PREFIXES,
    DEFAULT_EXPECTED_ROOT,
    DEFAULT_REQUIRED_JOINTS,
    DEFAULT_SCALE_TOLERANCE,
    validate_unreal_export,
)


def test_validate_unreal_export_success() -> None:
    report = validate_unreal_export(
        asset_name="SK_HeroCharacter",
        scale=1.0,
        skeleton_root=DEFAULT_EXPECTED_ROOT,
        joints=["root", "pelvis", "spine_01", "spine_02"],
    )

    assert report.is_valid
    assert report.scale_valid
    assert report.skeleton_valid
    assert report.naming_valid
    assert report.issues == ()


def test_validate_unreal_export_scale_failure() -> None:
    report = validate_unreal_export(
        asset_name="SK_HeroCharacter",
        scale=1.5,
        skeleton_root=DEFAULT_EXPECTED_ROOT,
        joints=DEFAULT_REQUIRED_JOINTS,
    )

    assert not report.scale_valid
    assert not report.is_valid
    assert any(issue.code == "SCALE_MISMATCH" for issue in report.issues)


def test_validate_unreal_export_skeleton_missing_joint() -> None:
    joints = [joint for joint in DEFAULT_REQUIRED_JOINTS if joint != "pelvis"]
    report = validate_unreal_export(
        asset_name="SK_HeroCharacter",
        scale=1.0,
        skeleton_root=DEFAULT_EXPECTED_ROOT,
        joints=joints,
    )

    assert not report.skeleton_valid
    assert not report.is_valid
    missing_issue = next(
        issue for issue in report.issues if issue.code == "SKELETON_JOINTS_MISSING"
    )
    assert "pelvis" in missing_issue.message


def test_validate_unreal_export_naming_rules() -> None:
    report = validate_unreal_export(
        asset_name="Hero Character",
        scale=1.0,
        skeleton_root=DEFAULT_EXPECTED_ROOT,
        joints=DEFAULT_REQUIRED_JOINTS,
        allowed_name_prefixes=DEFAULT_ALLOWED_PREFIXES,
        scale_tolerance=DEFAULT_SCALE_TOLERANCE,
    )

    assert not report.naming_valid
    assert not report.is_valid
    codes = {issue.code for issue in report.issues}
    assert "NAME_CONTAINS_SPACES" in codes
    assert "NAME_PREFIX_INVALID" in codes


def test_validate_unreal_export_custom_requirements() -> None:
    report = validate_unreal_export(
        asset_name="CHR_Minion",
        scale=2.54,
        skeleton_root="world",
        joints=["world", "hip"],
        expected_scale=2.54,
        scale_tolerance=0.0,
        allowed_name_prefixes=("CHR_",),
        required_joints=("world", "hip"),
        expected_root="world",
    )

    assert report.is_valid
    assert report.issues == ()
