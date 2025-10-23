"""Tests for the Maya playblast automation helper."""

from __future__ import annotations

import datetime as _dt
import shutil
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest

from libraries.creative.dcc.maya.playblast_tool import (
    PlayblastAutomationTool,
    PlayblastRequest,
    build_playblast_filename,
)
from libraries.creative.dcc.utils import normalize_frame_range, sanitize_token
from libraries.integrations.shotgrid.client import ShotgridClient


def _create_request(tmp_path: Path, **overrides: Any) -> PlayblastRequest:
    base = dict(
        project="One Piece",
        sequence="EP 01",
        shot="sh010",
        artist="Nami.Swan",
        camera="anim:cam_main",
        version=3,
        output_directory=Path(tmp_path / "playblasts"),
        format="mov",
        extra_metadata={"status": "pending"},
    )
    base.update(overrides)
    return PlayblastRequest(**base)


@pytest.mark.parametrize(
    "resolution",
    [
        (0, 1080),
        (1920, 0),
        (-1280, 720),
        (1920, -720),
        ("1920", "0"),
    ],
)
def test_playblast_request_rejects_invalid_resolution(
    tmp_path: Path, resolution: tuple[int | str, int | str]
) -> None:
    with pytest.raises(ValueError):
        _create_request(tmp_path, resolution=resolution)


@pytest.mark.parametrize(
    "extra_metadata",
    [
        ["not", "a", "mapping"],
        {1: "invalid-key"},
    ],
)
def test_playblast_request_rejects_invalid_extra_metadata(
    tmp_path: Path, extra_metadata: Any
) -> None:
    with pytest.raises(TypeError, match="extra_metadata must be a mapping with string keys"):
        _create_request(tmp_path, extra_metadata=extra_metadata)


def _fake_playblast(_: PlayblastRequest, target: Path, __: tuple[int, int]) -> Path:
    Path(target).write_bytes(b"playblast")
    return target


def _fake_empty_playblast(_: PlayblastRequest, __: Path, ___: tuple[int, int]) -> Any:
    return None


def _fake_invalid_playblast(_: PlayblastRequest, __: Path, ___: tuple[int, int]) -> Any:
    return 1234


def _fake_mismatch_playblast(
    _: PlayblastRequest, target: Path, __: tuple[int, int]
) -> Path:
    reported = target.parent / "reported.mov"
    Path(reported).write_bytes(b"playblast")
    return reported


def _fake_external_playblast(
    _: PlayblastRequest, target: Path, __: tuple[int, int]
) -> Path:
    outside = target.parent.parent / "external" / target.name
    outside.parent.mkdir(parents=True, exist_ok=True)
    Path(outside).write_bytes(b"playblast")
    return outside


class _ReviewRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, dict[str, Any]]] = []

    def upload(self, media_path: Path, metadata: dict[str, Any]) -> str:
        self.calls.append((media_path, metadata))
        return "review-001"


def test_build_playblast_filename_normalizes_tokens(tmp_path: Path) -> None:
    request = _create_request(tmp_path, version=7)
    timestamp = _dt.datetime(2024, 2, 11, 9, 30, 0)

    filename = build_playblast_filename(request, timestamp)

    expected_parts = [
        sanitize_token(request.project, fallback="UNKNOWN"),
        sanitize_token(request.sequence, fallback="UNKNOWN"),
        sanitize_token(request.shot, fallback="UNKNOWN"),
        sanitize_token(request.camera, fallback="UNKNOWN"),
        "V007",
        sanitize_token(request.artist, fallback="UNKNOWN"),
        timestamp.strftime("%Y%m%d"),
    ]
    assert filename == f"{'_'.join(expected_parts)}.mov"


def test_build_playblast_filename_uses_unknown_fallback(tmp_path: Path) -> None:
    request = _create_request(
        tmp_path,
        project="",
        sequence=None,
        shot="",
        camera="anim:cam_main",
        artist=None,
        version=1,
    )
    timestamp = _dt.datetime(2024, 5, 4, 15, 0, 0)

    filename = build_playblast_filename(request, timestamp)

    assert filename.startswith("UNKNOWN")
    assert sanitize_token("", fallback="UNKNOWN") in filename


@pytest.mark.parametrize(
    "format_value",
    [
        "../evil",
        "..\\evil",
        "mov;rm -rf",
        "gif..",
        "mp4?",
    ],
)
def test_build_playblast_filename_rejects_malicious_formats(
    tmp_path: Path, format_value: str
) -> None:
    request = _create_request(tmp_path, format=format_value)
    request.output_directory.mkdir(parents=True, exist_ok=True)
    timestamp = _dt.datetime(2024, 8, 1, 12, 0, 0)

    filename = build_playblast_filename(request, timestamp)
    resolved_output = (request.output_directory / filename).resolve()

    assert filename.endswith(".mov")
    assert resolved_output.parent == request.output_directory.resolve()


def test_execute_uses_timeline_when_frame_range_missing(tmp_path: Path) -> None:
    timeline_calls = 0

    def timeline() -> tuple[int, int]:
        nonlocal timeline_calls
        timeline_calls += 1
        return (101.2, 200.6)  # type: ignore[return-value]

    request = _create_request(tmp_path, frame_range=None)
    tool = PlayblastAutomationTool(
        timeline_query=timeline,
        playblast_callback=_fake_playblast,
        clock=lambda: _dt.datetime(2024, 5, 1, 10, 0, 0),
    )

    result = tool.execute(request)

    assert timeline_calls == 1
    assert result.frame_range == normalize_frame_range((101.2, 200.6))
    assert Path(result.output_path).exists()


def test_execute_registers_version_with_shotgrid(tmp_path: Path) -> None:
    client = ShotgridClient(sleep=lambda _: None)
    request = _create_request(tmp_path, description="Animation WIP")
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (1001, 1010),
        playblast_callback=_fake_playblast,
        clock=lambda: _dt.datetime(2024, 1, 2, 12, 0, 0),
        shotgrid_client=client,
    )

    result = tool.execute(request)

    versions = client.list_versions()
    assert len(versions) == 1
    version = versions[0]
    assert version["path"] == str(Path(result.output_path))
    assert version["code"] == Path(result.output_path).stem
    assert version["description"] == "Animation WIP"


def test_execute_uploads_to_review_service(tmp_path: Path) -> None:
    reviewer = _ReviewRecorder()
    request = _create_request(tmp_path, extra_metadata={"status": "blocking"})
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (1101, 1110),
        playblast_callback=_fake_playblast,
        clock=lambda: _dt.datetime(2024, 3, 15, 8, 0, 0),
        review_uploader=reviewer,
    )

    result = tool.execute(request)

    assert result.review_id == "review-001"
    assert reviewer.calls
    uploaded_path, metadata = reviewer.calls[0]
    assert uploaded_path == result.output_path
    assert metadata["frame_range_label"] == "1101-1110"
    assert metadata["version"] == "V003"
    assert metadata["status"] == "blocking"


def test_execute_validates_frame_range(tmp_path: Path) -> None:
    request = _create_request(tmp_path, frame_range=(120, 100))
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (1, 2),
        playblast_callback=_fake_playblast,
        clock=lambda: _dt.datetime(2024, 4, 1, 12, 0, 0),
    )

    with pytest.raises(ValueError):
        tool.execute(request)


def test_execute_rejects_missing_playblast_path(tmp_path: Path) -> None:
    request = _create_request(tmp_path)
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (1, 2),
        playblast_callback=_fake_empty_playblast,
        clock=lambda: _dt.datetime(2024, 5, 1, 9, 0, 0),
    )

    with pytest.raises(RuntimeError) as exc_info:
        tool.execute(request)

    assert "did not return an output path" in str(exc_info.value)


def test_execute_rejects_invalid_playblast_path_type(tmp_path: Path) -> None:
    request = _create_request(tmp_path)
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (1, 2),
        playblast_callback=_fake_invalid_playblast,
        clock=lambda: _dt.datetime(2024, 5, 1, 9, 0, 0),
    )

    with pytest.raises(RuntimeError) as exc_info:
        tool.execute(request)

    assert "unsupported path value" in str(exc_info.value)


def test_execute_rejects_external_playblast_path(tmp_path: Path) -> None:
    request = _create_request(tmp_path)
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (1, 2),
        playblast_callback=_fake_external_playblast,
        clock=lambda: _dt.datetime(2024, 5, 1, 9, 0, 0),
    )

    with pytest.raises(RuntimeError) as exc_info:
        tool.execute(request)

    assert "outside the requested directory" in str(exc_info.value)


def test_execute_normalizes_windows_style_directory(tmp_path: Path) -> None:
    windows_dir = Path(r"C:\\projects")
    request = _create_request(tmp_path, output_directory=windows_dir)
    timestamp = _dt.datetime(2024, 6, 1, 0, 0, 0)
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (200, 210),
        playblast_callback=lambda _req, target, _frame: target,
        clock=lambda: timestamp,
    )

    try:
        result = tool.execute(request)
        expected_filename = build_playblast_filename(request, timestamp)

        assert result.output_path == windows_dir / expected_filename
        assert PureWindowsPath(str(result.output_path)) == (
            PureWindowsPath(windows_dir) / expected_filename
        )
    finally:
        shutil.rmtree(windows_dir, ignore_errors=True)


def test_execute_prefers_reported_playblast_path(tmp_path: Path) -> None:
    request = _create_request(tmp_path)
    tool = PlayblastAutomationTool(
        timeline_query=lambda: (300, 310),
        playblast_callback=_fake_mismatch_playblast,
        clock=lambda: _dt.datetime(2024, 7, 1, 10, 0, 0),
    )

    result = tool.execute(request)

    expected_filename = build_playblast_filename(
        request, _dt.datetime(2024, 7, 1, 10, 0, 0)
    )
    default_target = request.output_directory / expected_filename
    reported_target = default_target.parent / "reported.mov"

    assert result.output_path == reported_target
    assert reported_target.exists()
