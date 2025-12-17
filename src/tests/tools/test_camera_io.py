from __future__ import annotations

import pytest

from libraries.creative.camera_io import (
    CameraPrim,
    ProjectionParameters,
    Timewarp,
    apply_timewarp,
    export_otio_timewarp,
    export_usd_camera,
    import_otio_timewarp,
    import_usd_camera,
)


@pytest.fixture()
def camera_prim() -> CameraPrim:
    transform = (
        (1.0, 0.0, 0.0, 12.0),
        (0.0, 1.0, 0.0, -4.0),
        (0.0, 0.0, 1.0, 3.5),
        (0.0, 0.0, 0.0, 1.0),
    )
    projection = ProjectionParameters(
        focal_length=35.0,
        horizontal_aperture=24.0,
        vertical_aperture=18.0,
        near_clip=0.25,
        far_clip=1000.0,
    )
    timewarp = Timewarp([(0.0, 0.0), (12.0, 10.0), (24.0, 22.0)])
    return CameraPrim(
        name="MainCamera",
        transform=transform,
        projection=projection,
        lens_distortion={"k1": 0.1, "k2": -0.02},
        timewarp=timewarp,
    )


def test_usd_round_trip_preserves_projection(camera_prim: CameraPrim) -> None:
    payload = export_usd_camera(camera_prim)
    reconstructed = import_usd_camera(payload)

    assert reconstructed.transform == camera_prim.transform
    assert reconstructed.projection == camera_prim.projection
    assert reconstructed.lens_distortion == camera_prim.lens_distortion
    assert reconstructed.timewarp.keyframes == camera_prim.timewarp.keyframes


def test_otio_timewarp_round_trip_matches_mapping() -> None:
    timewarp = Timewarp([(0.0, 0.0), (10.0, 12.0)])
    otio = export_otio_timewarp(timewarp)
    restored = import_otio_timewarp(otio)

    assert restored.map_time(0.0) == pytest.approx(timewarp.map_time(0.0))
    assert restored.map_time(5.0) == pytest.approx(timewarp.map_time(5.0))
    assert restored.map_time(10.0) == pytest.approx(timewarp.map_time(10.0))


def test_timewarp_application_matches_frame_mapping(camera_prim: CameraPrim) -> None:
    frames = [0.0, 6.0, 12.0, 18.0, 24.0]
    mapped = apply_timewarp(camera_prim.timewarp, frames)

    assert mapped == pytest.approx([0.0, 5.0, 10.0, 16.0, 22.0])
