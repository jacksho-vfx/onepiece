from __future__ import annotations

from libraries.platform.media.ffmpeg.wrapper import BurnInMetadata, build_burnin_filter


def test_build_burnin_filter_increments_y_offsets() -> None:
    burnins = [
        BurnInMetadata(
            shot="sh010",
            version="v001",
            frame_range="1001-1100",
            user="nami",
        ),
        BurnInMetadata(
            shot="sh020",
            version="v002",
            frame_range="1101-1200",
            user="robin",
        ),
        BurnInMetadata(
            shot="sh030",
            version="v003",
            frame_range="1201-1300",
            user="franky",
        ),
    ]

    result = build_burnin_filter(burnins)
    overlays = result.split(",")

    assert len(overlays) == 3
    expected_offsets = [24, 56, 88]
    for overlay, expected_offset in zip(overlays, expected_offsets):
        assert f":y={expected_offset}:" in overlay
