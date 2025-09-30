"""Tests for the dailies CLI command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app
from onepiece.review.dailies import DailiesClip

runner = CliRunner()


@pytest.fixture()
def sample_clip(tmp_path: Path) -> DailiesClip:
    media = tmp_path / "shot.mov"
    media.write_text("placeholder", encoding="utf-8")
    return DailiesClip(
        shot="sh010",
        version="v001",
        source_path=str(media),
        frame_range="1001-1010",
        user="artist",
        duration_seconds=5.0,
    )


def test_dailies_playlist_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_clip: DailiesClip
) -> None:
    output = tmp_path / "dailies.mov"
    manifest_path = output.with_name(f"{output.name}.manifest.json")

    monkeypatch.setattr("onepiece.review.dailies.get_shotgrid_client", lambda: object())
    monkeypatch.setattr(
        "onepiece.review.dailies.fetch_playlist_versions",
        lambda client, project, playlist: [sample_clip],
    )

    recorded: dict[str, Any] = {}

    def _fake_run_ffmpeg(
        concat_file: Path, render_path: Path, *, codec: str, burnins: Any
    ) -> subprocess.CompletedProcess[Any]:
        recorded["concat_file"] = concat_file
        recorded["render_path"] = render_path
        recorded["codec"] = codec
        recorded["burnins"] = burnins
        render_path.write_text("rendered", encoding="utf-8")
        return subprocess.CompletedProcess(["ffmpeg"], 0)

    monkeypatch.setattr(
        "onepiece.review.dailies.run_ffmpeg_concat",
        _fake_run_ffmpeg,
    )

    result = runner.invoke(
        app,
        [
            "review",
            "dailies",
            "--project",
            "Demo",
            "--playlist",
            "Client",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert output.exists()
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["output"] == str(output)
    assert manifest["codec"] == "prores"
    assert manifest["clips"][0]["shot"] == "sh010"

    assert "Compiled 1 clips (5.00s)" in result.stdout

    assert recorded["codec"] == "prores"
    burnins = recorded["burnins"]
    assert burnins is not None
    assert burnins[0].shot == "sh010"


def test_dailies_no_versions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    output = tmp_path / "dailies.mov"

    monkeypatch.setattr("onepiece.review.dailies.get_shotgrid_client", lambda: object())
    monkeypatch.setattr(
        "onepiece.review.dailies.fetch_today_approved_versions",
        lambda client, project: [],
    )

    result = runner.invoke(
        app,
        [
            "review",
            "dailies",
            "--project",
            "Demo",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 1
    assert "No versions found" in result.stdout
    assert not output.exists()


def test_dailies_ffmpeg_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_clip: DailiesClip
) -> None:
    output = tmp_path / "dailies.mov"

    monkeypatch.setattr("onepiece.review.dailies.get_shotgrid_client", lambda: object())
    monkeypatch.setattr(
        "onepiece.review.dailies.fetch_today_approved_versions",
        lambda client, project: [sample_clip],
    )

    def _raise_ffmpeg(*_: Any, **__: Any) -> subprocess.CompletedProcess[Any]:
        raise subprocess.CalledProcessError(1, ["ffmpeg"], stderr="boom")

    monkeypatch.setattr(
        "onepiece.review.dailies.run_ffmpeg_concat",
        _raise_ffmpeg,
    )

    result = runner.invoke(
        app,
        [
            "review",
            "dailies",
            "--project",
            "Demo",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2
    assert "FFmpeg failed" in (result.stderr or result.stdout)
    assert not output.exists()
