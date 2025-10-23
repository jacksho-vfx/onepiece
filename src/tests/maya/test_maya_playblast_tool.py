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


def _fake_playblast(_: PlayblastRequest, target: Path, __: tuple[int, int]) -> Path:
    Path(target).write_bytes(b"playblast")
    return target


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
