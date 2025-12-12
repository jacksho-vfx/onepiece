"""Cinema 4D camera publisher that bakes lens distortion metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from tools.camera_io import (
    CameraPrim,
    ProjectionParameters,
    Timewarp,
    bake_lens_metadata,
    export_usd_camera,
)


def publish_camera_from_c4d(
    _doc: object,
    camera_object: object,
    output_path: str | Path,
    lens_metadata: Mapping[str, float],
) -> Path:
    projection = ProjectionParameters(
        focal_length=float(camera_object["focus"]),  # type: ignore[index]
        horizontal_aperture=float(camera_object["aperture_horizontal"]),  # type: ignore[index]
        vertical_aperture=float(camera_object["aperture_vertical"]),  # type: ignore[index]
    )
    world_matrix = getattr(camera_object, "GetMg")()  # type: ignore[attr-defined]
    transform = (
        (float(world_matrix[0][0]), float(world_matrix[0][1]), float(world_matrix[0][2]), float(world_matrix[0][3])),
        (float(world_matrix[1][0]), float(world_matrix[1][1]), float(world_matrix[1][2]), float(world_matrix[1][3])),
        (float(world_matrix[2][0]), float(world_matrix[2][1]), float(world_matrix[2][2]), float(world_matrix[2][3])),
        (0.0, 0.0, 0.0, 1.0),
    )

    prim = CameraPrim(
        name=camera_object.GetName(),  # type: ignore[attr-defined]
        transform=transform,
        projection=projection,
        lens_distortion=bake_lens_metadata(lens_metadata),
        timewarp=Timewarp([(0.0, 0.0), (1.0, 1.0)]),
    )

    payload = export_usd_camera(prim)
    path = Path(output_path)
    path.write_text(str(payload))
    return path
