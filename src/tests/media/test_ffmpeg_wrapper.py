from __future__ import annotations

from libraries.platform.media.ffmpeg.wrapper import (
    BurnInMetadata,
    BurnInOptions,
    build_burnin_filter,
)


def test_build_burnin_filter_increments_y_offsets() -> None:
    burnins = [
        BurnInMetadata(
            show="onepiece",
            shot="sh010",
            version="v001",
            date="2024-01-01",
            frame_range="1001-1100",
            user="nami",
        ),
        BurnInMetadata(
            show="onepiece",
            shot="sh020",
            version="v002",
            date="2024-01-01",
            frame_range="1101-1200",
            user="robin",
        ),
        BurnInMetadata(
            show="onepiece",
            shot="sh030",
            version="v003",
            date="2024-01-01",
            frame_range="1201-1300",
            user="franky",
        ),
    ]

    result = build_burnin_filter(burnins)
    overlays = result.split(",")

    assert len(overlays) == 5
    expected_offsets = [24, 200, 376]
    for overlay, expected_offset in zip(overlays, expected_offsets):
        assert f":y={expected_offset}:" in overlay


def test_build_burnin_filter_returns_comma_separated_overlays() -> None:
    burnins = [
        BurnInMetadata(
            show="onepiece",
            shot="sh040",
            version="v004",
            date="2024-01-01",
            frame_range="1301-1400",
            user="luffy",
        ),
        BurnInMetadata(
            show="onepiece",
            shot="sh050",
            version="v005",
            date="2024-01-01",
            frame_range="1401-1500",
            user="zoro",
        ),
    ]

    result = build_burnin_filter(burnins)

    assert "," in result
    assert "Show\\: onepiece" in result
    assert "Shot\\: sh040" in result
    assert "Shot\\: sh050" in result


def test_build_burnin_filter_matches_expected_layout_snapshot() -> None:
    burnins = [
        BurnInMetadata(
            show="Grand Line",
            shot="sh060",
            version="v010",
            date="2024-05-01",
            frame_range="1501-1600",
            user="usopp",
        )
    ]

    result = build_burnin_filter(
        burnins,
        options=BurnInOptions(
            fontfile="/Library/Fonts/SourceCodePro.ttf",
            fontsize=20,
            margin=32,
            slate_position="top-right",
            counter_position="bottom-left",
            frame_rate=25.0,
        ),
    )

    assert (
        result
        == "drawtext=text='Show\\: Grand Line\\nShot\\: sh060\\nVersion\\: v010\\nUser\\: usopp\\nDate\\: 2024-05-01\\nFrames\\: 1501-1600':x=w-tw-32:y=32:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6:line_spacing=4:fontfile='/Library/Fonts/SourceCodePro.ttf',"
        "drawtext=timecode='00\\:00\\:00\\:00':r=25.0:x=32:y=h-th-32:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6:fontfile='/Library/Fonts/SourceCodePro.ttf',"
        "drawtext=text='Frame %{n}':x=32:y=h-th-60:fontsize=20:fontcolor=white:box=1:boxcolor=black@0.6:fontfile='/Library/Fonts/SourceCodePro.ttf'"
    )


def test_build_burnin_filter_adds_timecode_and_frame_counters() -> None:
    burnins = [
        BurnInMetadata(
            show="East Blue",
            shot="sh070",
            version="v020",
            date="2024-06-01",
            frame_range="1701-1800",
            user="sanji",
        )
    ]

    result = build_burnin_filter(burnins)
    overlays = result.split(",")

    assert any(overlay.startswith("drawtext=timecode=") for overlay in overlays)
    frame_overlay = next(overlay for overlay in overlays if "Frame %{n}" in overlay)
    assert ":y=56:" in frame_overlay or ":y=h-th-56:" in frame_overlay
