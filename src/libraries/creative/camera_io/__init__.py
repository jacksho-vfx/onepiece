"""Utilities for exchanging camera data between USD and OTIO contexts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

Matrix4x4 = tuple[tuple[float, float, float, float], ...]


def _validate_matrix(matrix: Sequence[Sequence[float]]) -> Matrix4x4:
    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise ValueError("Camera transforms must be 4x4 matrices")
    return tuple(tuple(float(value) for value in row) for row in matrix)  # type: ignore[misc]


@dataclass(frozen=True)
class ProjectionParameters:
    """Projection settings describing the camera frustum."""

    focal_length: float
    horizontal_aperture: float
    vertical_aperture: float
    near_clip: float = 0.1
    far_clip: float = 10_000.0

    def to_dict(self) -> dict[str, float]:
        return {
            "focalLength": float(self.focal_length),
            "horizontalAperture": float(self.horizontal_aperture),
            "verticalAperture": float(self.vertical_aperture),
            "nearClip": float(self.near_clip),
            "farClip": float(self.far_clip),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, float]) -> "ProjectionParameters":
        return cls(
            focal_length=float(payload["focalLength"]),
            horizontal_aperture=float(payload["horizontalAperture"]),
            vertical_aperture=float(payload["verticalAperture"]),
            near_clip=float(payload.get("nearClip", 0.1)),
            far_clip=float(payload.get("farClip", 10_000.0)),
        )


@dataclass
class Timewarp:
    """Linear timewarp mapping timeline time to source time."""

    keyframes: list[tuple[float, float]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.keyframes = [
            (float(timeline_time), float(source_time))
            for timeline_time, source_time in sorted(
                self.keyframes, key=lambda item: item[0]
            )
        ]

    def map_time(self, timeline_time: float) -> float:
        if not self.keyframes:
            return float(timeline_time)

        timeline_time = float(timeline_time)
        if timeline_time <= self.keyframes[0][0]:
            return self.keyframes[0][1]
        if timeline_time >= self.keyframes[-1][0]:
            return self.keyframes[-1][1]

        for (t0, s0), (t1, s1) in zip(self.keyframes, self.keyframes[1:]):
            if t0 <= timeline_time <= t1:
                alpha = (timeline_time - t0) / (t1 - t0)
                return s0 + alpha * (s1 - s0)
        return float(timeline_time)

    def to_otio(self) -> dict[str, object]:
        return {
            "schema": "LinearTimewarp",
            "keyframes": [
                {"timeline_time": timeline_time, "source_time": source_time}
                for timeline_time, source_time in self.keyframes
            ],
        }

    @classmethod
    def from_otio(cls, payload: Mapping[str, object]) -> "Timewarp":
        keyframes = [
            (
                float(entry["timeline_time"]),
                float(entry["source_time"]),
            )
            for entry in payload.get("keyframes", [])  # type: ignore[attr-defined]
        ]
        return cls(keyframes)


@dataclass
class CameraPrim:
    """Lightweight representation of a USD camera prim."""

    name: str
    transform: Matrix4x4
    projection: ProjectionParameters
    lens_distortion: dict[str, float] = field(default_factory=dict)
    timewarp: Timewarp = field(default_factory=Timewarp)

    def __post_init__(self) -> None:
        self.transform = _validate_matrix(self.transform)

    def baked_metadata(self) -> dict[str, object]:
        return {
            "lens_distortion": {
                key: float(value) for key, value in self.lens_distortion.items()
            },
            "timewarp": self.timewarp.to_otio(),
        }


def export_usd_camera(camera: CameraPrim) -> dict[str, object]:
    """Serialize a camera prim into a USD-friendly payload."""

    return {
        "type": "Camera",
        "name": camera.name,
        "transform": camera.transform,
        "attributes": camera.projection.to_dict(),
        "metadata": camera.baked_metadata(),
    }


def import_usd_camera(payload: Mapping[str, object]) -> CameraPrim:
    if payload.get("type") != "Camera":
        raise ValueError("USD payload does not describe a Camera prim")

    projection = ProjectionParameters.from_dict(payload["attributes"])  # type: ignore[arg-type]
    metadata = payload.get("metadata", {})
    lens_distortion = metadata.get("lens_distortion", {})  # type: ignore[attr-defined]
    timewarp_payload = metadata.get("timewarp", {"keyframes": []})  # type: ignore[attr-defined]
    return CameraPrim(
        name=str(payload.get("name", "Camera")),
        transform=_validate_matrix(payload["transform"]),  # type: ignore[arg-type]
        projection=projection,
        lens_distortion={
            str(key): float(value) for key, value in lens_distortion.items()
        },
        timewarp=Timewarp.from_otio(timewarp_payload),
    )


def export_otio_timewarp(timewarp: Timewarp) -> dict[str, object]:
    """Encode a timewarp as a minimal OTIO data structure."""

    return timewarp.to_otio()


def import_otio_timewarp(payload: Mapping[str, object]) -> Timewarp:
    """Reconstruct a :class:`Timewarp` from OTIO-style data."""

    return Timewarp.from_otio(payload)


def bake_lens_metadata(
    distortion_coefficients: Mapping[str, float]
) -> dict[str, float]:
    """Normalize lens distortion metadata for publication."""

    return {str(key): float(value) for key, value in distortion_coefficients.items()}


def apply_timewarp(timewarp: Timewarp, times: Iterable[float]) -> list[float]:
    """Map a sequence of timeline times through the provided timewarp."""

    return [timewarp.map_time(time) for time in times]
