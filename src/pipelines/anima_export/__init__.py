"""Anima USD skel exporter with motion baking and rig validation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class AnimaExportError(RuntimeError):
    """Raised when actor payloads cannot be serialised into USD skel stubs."""


@dataclass(frozen=True)
class SkeletonJoint:
    """A joint in an Anima actor skeleton."""

    name: str
    parent: str | None = None
    rest_transform: Sequence[float] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.name:
            msg = "Skeleton joints require a stable name"
            raise ValueError(msg)
        if self.parent == "":
            object.__setattr__(self, "parent", None)


@dataclass(frozen=True)
class PoseSample:
    """Animation pose keyed by frame index."""

    frame: int
    transforms: Mapping[str, Sequence[float]]

    def __post_init__(self) -> None:
        if self.frame < 0:
            msg = "Pose frames must be non-negative"
            raise ValueError(msg)
        object.__setattr__(self, "transforms", dict(self.transforms))


@dataclass(frozen=True)
class AnimationClip:
    """Animation clip to bake into USD skel AnimationSource payloads."""

    name: str
    fps: float
    samples: Sequence[PoseSample]

    def __post_init__(self) -> None:
        if not self.name:
            msg = "Animation clips require a name"
            raise ValueError(msg)
        if self.fps <= 0:
            msg = "Animation clips require a positive fps"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "samples",
            tuple(sorted(self.samples, key=lambda sample: sample.frame)),
        )

    @property
    def duration_seconds(self) -> float:
        if not self.samples:
            return 0.0
        last_frame = self.samples[-1].frame
        return last_frame / self.fps


@dataclass(frozen=True)
class AnimaActor:
    """Source actor payload aggregated from Anima project files."""

    name: str
    skeleton: Sequence[SkeletonJoint]
    clips: Sequence[AnimationClip]
    crowd_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            msg = "Actors require a name"
            raise ValueError(msg)
        if not self.skeleton:
            msg = "Actors require at least one skeleton joint"
            raise ValueError(msg)
        skeleton = tuple(self.skeleton)
        names = {joint.name for joint in skeleton}
        if len(names) != len(skeleton):
            msg = "Duplicate joint names detected in actor skeleton"
            raise ValueError(msg)
        object.__setattr__(self, "skeleton", skeleton)
        object.__setattr__(self, "clips", tuple(self.clips))
        object.__setattr__(self, "crowd_metadata", dict(self.crowd_metadata))


@dataclass(frozen=True)
class UsdSkelExportResult:
    """Details for exported USD skel payload."""

    usd_path: Path
    skeleton_prim: str
    clip_prim_paths: Mapping[str, str]
    lods: Mapping[str, Sequence[str]]
    baked_fps: int | None
    metadata: Mapping[str, Any]


class AnimaUsdExporter:
    """Convert Anima actors into USD skel stubs ready for downstream DCCs."""

    def __init__(
        self,
        *,
        skeleton_prim: str = "/World/AnimaSkeleton",
        lod_levels: Sequence[int] | None = None,
        bake_fps: int | None = None,
    ) -> None:
        self.skeleton_prim = skeleton_prim
        self.default_lod_levels = tuple(lod_levels or (0,))
        self._validate_lod_levels(self.default_lod_levels)
        self.bake_fps = bake_fps
        if bake_fps is not None:
            self._validate_bake_rate(bake_fps)

    def export(
        self,
        actor: AnimaActor,
        output_path: str | Path,
        *,
        lod_levels: Sequence[int] | None = None,
        bake_fps: int | None = None,
    ) -> UsdSkelExportResult:
        levels = tuple(lod_levels or self.default_lod_levels)
        self._validate_lod_levels(levels)
        bake_rate = bake_fps if bake_fps is not None else self.bake_fps
        if bake_rate is not None:
            self._validate_bake_rate(bake_rate)

        baked_clips = [
            self._bake_clip(clip, bake_rate) if bake_rate else clip
            for clip in actor.clips
        ]
        skeleton_variants = self._generate_lods(actor.skeleton, levels)

        payload = {
            "kind": "usdskel",
            "actor": actor.name,
            "skeletonPrim": self.skeleton_prim,
            "skeleton": [self._joint_snapshot(joint) for joint in actor.skeleton],
            "lodJoints": skeleton_variants,
            "animationClips": [self._clip_snapshot(clip) for clip in baked_clips],
            "crowdMetadata": dict(actor.crowd_metadata),
            "bakedFps": bake_rate,
        }

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        except OSError as exc:  # pragma: no cover - filesystem failure guard
            msg = f"Unable to write USD skel payload to {path}: {exc}"
            raise AnimaExportError(msg) from exc

        clip_prim_paths = {
            clip.name: f"{self.skeleton_prim}/Animations/{clip.name}"
            for clip in baked_clips
        }
        return UsdSkelExportResult(
            usd_path=path,
            skeleton_prim=self.skeleton_prim,
            clip_prim_paths=clip_prim_paths,
            lods={
                name: [joint["name"] for joint in joints]
                for name, joints in skeleton_variants.items()
            },
            baked_fps=bake_rate,
            metadata={"crowd": dict(actor.crowd_metadata)},
        )

    def _validate_lod_levels(self, levels: Sequence[int]) -> None:
        if not levels:
            msg = "At least one LOD level must be provided"
            raise ValueError(msg)
        if any(level < 0 for level in levels):
            msg = "LOD levels must be zero or positive integers"
            raise ValueError(msg)

    def _validate_bake_rate(self, bake_rate: int) -> None:
        if bake_rate not in {30, 60}:
            msg = "Bake fps must be 30 or 60 to ensure deterministic motion resampling"
            raise ValueError(msg)

    def _joint_snapshot(self, joint: SkeletonJoint) -> dict[str, Any]:
        return {
            "name": joint.name,
            "parent": joint.parent,
            "rest": list(joint.rest_transform),
        }

    def _clip_snapshot(self, clip: AnimationClip) -> dict[str, Any]:
        return {
            "name": clip.name,
            "fps": clip.fps,
            "samples": [
                {"frame": sample.frame, "transforms": sample.transforms}
                for sample in clip.samples
            ],
        }

    def _generate_lods(
        self, skeleton: Sequence[SkeletonJoint], levels: Sequence[int]
    ) -> dict[str, list[dict[str, Any]]]:
        lods: dict[str, list[dict[str, Any]]] = {}
        for level in levels:
            step = max(1, level + 1)
            lod_key = f"lod{level}"
            lods[lod_key] = [self._joint_snapshot(joint) for joint in skeleton[::step]]
        return lods

    def _bake_clip(self, clip: AnimationClip, target_fps: int) -> AnimationClip:
        if not clip.samples:
            return clip
        duration = clip.duration_seconds
        frame_total = max(1, int(round(duration * target_fps)) + 1)
        baked_samples: list[PoseSample] = []
        for baked_frame in range(frame_total):
            time_seconds = baked_frame / target_fps
            baked_samples.append(
                PoseSample(
                    frame=baked_frame,
                    transforms=self._interpolate_pose(clip, time_seconds),
                )
            )
        return AnimationClip(
            name=clip.name, fps=float(target_fps), samples=baked_samples
        )

    def _interpolate_pose(
        self, clip: AnimationClip, time_seconds: float
    ) -> dict[str, list[float]]:
        samples = list(clip.samples)
        if time_seconds <= 0 or len(samples) == 1:
            return {
                name: list(values) for name, values in samples[0].transforms.items()
            }

        source_time = [sample.frame / clip.fps for sample in samples]
        if time_seconds >= source_time[-1]:
            return {
                name: list(values) for name, values in samples[-1].transforms.items()
            }

        for index, start_time in enumerate(source_time[:-1]):
            end_time = source_time[index + 1]
            if start_time <= time_seconds <= end_time:
                alpha = (time_seconds - start_time) / (end_time - start_time)
                start_transforms = samples[index].transforms
                end_transforms = samples[index + 1].transforms
                blended: dict[str, list[float]] = {}
                joint_names = set(start_transforms).union(end_transforms)
                for joint_name in joint_names:
                    start_value = start_transforms.get(joint_name)
                    end_value = end_transforms.get(joint_name)
                    if start_value is None:
                        blended[joint_name] = list(end_value or [])
                        continue
                    if end_value is None:
                        blended[joint_name] = list(start_value)
                        continue
                    blended[joint_name] = self._lerp(start_value, end_value, alpha)
                return blended

        return {name: list(values) for name, values in samples[-1].transforms.items()}

    def _lerp(
        self, start: Sequence[float], end: Sequence[float], alpha: float
    ) -> list[float]:
        if len(start) != len(end):
            msg = "Pose interpolation requires matching component counts"
            raise AnimaExportError(msg)
        return [(1 - alpha) * float(a) + alpha * float(b) for a, b in zip(start, end)]


def load_export(path: str | Path) -> Any:
    """Load an exported USD skel stub from disk."""

    data = json.loads(Path(path).read_text())
    if data.get("kind") != "usdskel":
        msg = "Export payload is not marked as a USD skel stub"
        raise AnimaExportError(msg)
    return data


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of a rig compatibility validation."""

    rig: str
    compatible: bool
    missing_joints: tuple[str, ...]
    unexpected_joints: tuple[str, ...]


_EXPECTED_JOINTS: dict[str, set[str]] = {
    "manny": {
        "root",
        "pelvis",
        "spine_01",
        "spine_02",
        "spine_03",
        "neck_01",
        "head",
        "clavicle_l",
        "clavicle_r",
        "upperarm_l",
        "upperarm_r",
        "lowerarm_l",
        "lowerarm_r",
        "hand_l",
        "hand_r",
        "thigh_l",
        "thigh_r",
        "calf_l",
        "calf_r",
        "foot_l",
        "foot_r",
    },
    "quinn": {
        "root",
        "pelvis",
        "spine_01",
        "spine_02",
        "spine_03",
        "neck_01",
        "head",
        "clavicle_l",
        "clavicle_r",
        "upperarm_l",
        "upperarm_r",
        "lowerarm_l",
        "lowerarm_r",
        "hand_l",
        "hand_r",
        "thigh_l",
        "thigh_r",
        "calf_l",
        "calf_r",
        "foot_l",
        "foot_r",
        "ball_l",
        "ball_r",
    },
}


def validate_skeleton(
    joint_names: Iterable[str], rig: str = "manny"
) -> ValidationReport:
    """Validate joints against the expected Unreal rig targets."""

    rig_key = rig.lower()
    if rig_key not in _EXPECTED_JOINTS:
        msg = f"Unknown Unreal rig '{rig}'"
        raise KeyError(msg)

    expected = _EXPECTED_JOINTS[rig_key]
    provided = set(joint_names)
    missing = tuple(sorted(expected - provided))
    unexpected = tuple(sorted(provided - expected))
    return ValidationReport(
        rig=rig_key,
        compatible=not missing and not unexpected,
        missing_joints=missing,
        unexpected_joints=unexpected,
    )


def validate_export(path: str | Path, rig: str = "manny") -> ValidationReport:
    """Load an exported USD skel file and check it against the given rig."""

    payload = load_export(path)
    joint_names = [joint["name"] for joint in payload.get("skeleton", [])]
    return validate_skeleton(joint_names, rig=rig)


__all__ = [
    "AnimaActor",
    "AnimaExportError",
    "AnimaUsdExporter",
    "AnimationClip",
    "PoseSample",
    "SkeletonJoint",
    "UsdSkelExportResult",
    "ValidationReport",
    "load_export",
    "validate_export",
    "validate_skeleton",
]
