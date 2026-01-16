from __future__ import annotations

from pathlib import Path

import pytest

from pipelines.anima_export import (
    AnimaActor,
    AnimationClip,
    AnimaUsdExporter,
    PoseSample,
    SkeletonJoint,
    load_export,
    validate_export,
    validate_skeleton,
)


@pytest.fixture
def sample_actor(tmp_path: Path) -> AnimaActor:
    joints = [
        SkeletonJoint(name="root"),
        SkeletonJoint(name="spine_01", parent="root"),
        SkeletonJoint(name="neck_01", parent="spine_01"),
        SkeletonJoint(name="head", parent="neck_01"),
    ]
    clip = AnimationClip(
        name="idle",
        fps=24,
        samples=[
            PoseSample(frame=0, transforms={"root": [0.0, 0.0, 0.0]}),
            PoseSample(frame=12, transforms={"root": [0.0, 1.0, 0.0]}),
        ],
    )
    return AnimaActor(
        name="crowd_agent",
        skeleton=joints,
        clips=[clip],
        crowd_metadata={"agentType": "pedestrian", "variation": 3},
    )


def test_exporter_generates_usdskel_payload(
    tmp_path: Path, sample_actor: AnimaActor
) -> None:
    exporter = AnimaUsdExporter(lod_levels=(0, 1), bake_fps=30)
    destination = tmp_path / "crowd.usd"

    result = exporter.export(sample_actor, destination)
    payload = load_export(destination)

    assert destination.exists()
    assert payload["kind"] == "usdskel"
    assert set(payload["lodJoints"]) == {"lod0", "lod1"}
    assert result.baked_fps == 30

    baked_clip = payload["animationClips"][0]
    assert baked_clip["fps"] == 30
    assert len(baked_clip["samples"]) > len(sample_actor.clips[0].samples)

    loaded = validate_export(destination, rig="manny")
    assert loaded.missing_joints  # head missing etc.


def test_motion_bake_interpolates_to_target_rate(
    tmp_path: Path, sample_actor: AnimaActor
) -> None:
    clip = AnimationClip(
        name="walk",
        fps=10,
        samples=[
            PoseSample(frame=0, transforms={"root": [0.0, 0.0, 0.0]}),
            PoseSample(frame=10, transforms={"root": [10.0, 0.0, 0.0]}),
        ],
    )
    actor = AnimaActor(
        name="walker",
        skeleton=sample_actor.skeleton,
        clips=[clip],
    )
    exporter = AnimaUsdExporter()

    destination = tmp_path / "baked.usd"
    exporter.export(actor, destination, bake_fps=60)
    payload = load_export(destination)

    baked_clip = payload["animationClips"][0]
    mid_pose = baked_clip["samples"][30]["transforms"]["root"][0]
    assert pytest.approx(mid_pose, rel=1e-3) == 5.0
    assert payload["bakedFps"] == 60


def test_validation_highlights_missing_targets(sample_actor: AnimaActor) -> None:
    # Drop feet to trigger missing joint reporting
    joint_names = [joint.name for joint in sample_actor.skeleton]
    report = validate_skeleton(joint_names, rig="manny")

    assert not report.compatible
    assert "foot_l" in report.missing_joints
    assert "foot_r" in report.missing_joints
    assert report.unexpected_joints == ()
