"""Helper for publishing camera prims from Nuke with baked lens metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from libraries.creative.camera_io import (
    CameraPrim,
    ProjectionParameters,
    Timewarp,
    bake_lens_metadata,
    export_usd_camera,
)
from libraries.metrics.usd import USDMetricClient

_metrics = USDMetricClient()


def _build_transform_from_knobs(
    camera_node: object,
) -> tuple[tuple[float, float, float, float], ...]:
    translate = camera_node["translate"].value()  # type: ignore[index]
    return (
        (1.0, 0.0, 0.0, translate[0]),
        (0.0, 1.0, 0.0, translate[1]),
        (0.0, 0.0, 1.0, translate[2]),
        (0.0, 0.0, 0.0, 1.0),
    )


def publish_camera_from_nuke(
    nuke_module: object,
    camera_name: str,
    output_path: str | Path,
    lens_metadata: Mapping[str, float],
) -> Path:
    with _metrics.time_block(
        dcc="nuke",
        stage="publish_camera",
        sequence=None,
        asset=camera_name,
        metadata={"output_path": str(output_path)},
    ):
        camera_node = nuke_module.toNode(camera_name)  # type: ignore[attr-defined]
        projection = ProjectionParameters(
            focal_length=float(camera_node["focal"].value()),  # type: ignore[index]
            horizontal_aperture=float(camera_node["haperture"].value()),  # type: ignore[index]
            vertical_aperture=float(camera_node["vaperture"].value()),  # type: ignore[index]
        )
        timewarp = Timewarp([(0.0, 0.0), (1.0, 1.0)])
        prim = CameraPrim(
            name=camera_name,
            transform=_build_transform_from_knobs(camera_node),
            projection=projection,
            lens_distortion=bake_lens_metadata(lens_metadata),
            timewarp=timewarp,
        )

        payload = export_usd_camera(prim)
        path = Path(output_path)
        path.write_text(str(payload))
    return path
