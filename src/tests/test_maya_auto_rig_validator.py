from __future__ import annotations

from libraries.dcc.maya.auto_rig_validator import (
    DEFAULT_CONTROL_PREFIXES,
    DEFAULT_JOINT_PREFIXES,
    validate_rig_import,
)


def test_validate_rig_import_success():
    report = validate_rig_import(
        rig_name="HeroRig",
        joints=["JNT_root", "JNT_spine", "JNT_chest"],
        hierarchy=[("JNT_root", "JNT_spine"), ("JNT_spine", "JNT_chest")],
        controls={
            "CTL_Main": {"visibility": True, "rigScale": 1.0},
            "CTL_COG": {"tx": 0.0},
        },
        required_control_attributes={"CTL_Main": ("visibility", "rigScale")},
    )

    assert report.is_valid
    assert report.naming_valid
    assert report.hierarchy_valid
    assert report.controls_valid
    assert report.issues == ()


def test_validate_rig_import_reports_bad_naming():
    report = validate_rig_import(
        rig_name="HeroRig",
        joints=["root", "JNT_spine"],
        hierarchy=[("JNT_root", "JNT_spine")],
        controls=["Main_CTRL"],
        allowed_joint_prefixes=DEFAULT_JOINT_PREFIXES,
        allowed_control_prefixes=DEFAULT_CONTROL_PREFIXES,
        required_control_attributes={},
    )

    assert not report.naming_valid
    assert any(issue.code == "JOINT_BAD_PREFIX" for issue in report.issues)
    assert any(issue.code == "CONTROL_BAD_PREFIX" for issue in report.issues)



def test_validate_rig_import_reports_missing_hierarchy():
    report = validate_rig_import(
        rig_name="HeroRig",
        joints=["JNT_root", "JNT_spine"],
        hierarchy=[("JNT_root", "JNT_spine")],
        controls={"CTL_Main": {"visibility": True}},
        required_hierarchy=[("JNT_root", "JNT_spine"), ("JNT_spine", "JNT_chest")],
        required_control_attributes={"CTL_Main": ("visibility",)},
    )

    assert not report.hierarchy_valid
    assert any(
        issue.code == "HIERARCHY_MISSING_RELATIONSHIP" for issue in report.issues
    )



def test_validate_rig_import_reports_missing_control_attribute():
    report = validate_rig_import(
        rig_name="HeroRig",
        joints=["JNT_root", "JNT_spine"],
        hierarchy=[("JNT_root", "JNT_spine")],
        controls={"CTL_Main": {"visibility": True}},
        required_control_attributes={"CTL_Main": ("visibility", "rigScale")},
    )

    assert not report.controls_valid
    assert any(
        issue.code == "CONTROL_MISSING_ATTRIBUTE" for issue in report.issues
    )



def test_validate_rig_import_detects_duplicate_names():
    report = validate_rig_import(
        rig_name="HeroRig",
        joints=["JNT_root", "JNT_root"],
        hierarchy=[("JNT_root", "JNT_root")],
        controls=["CTL_Main", "CTL_Main"],
        required_hierarchy=(),
        required_control_attributes={},
    )

    duplicate_codes = {issue.code for issue in report.issues}
    assert "JOINT_DUPLICATE_NAME" in duplicate_codes
    assert "CONTROL_DUPLICATE_NAME" in duplicate_codes
