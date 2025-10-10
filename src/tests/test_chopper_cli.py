from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apps.chopper.app import app
from apps.chopper.renderer import Scene


def test_render_reports_invalid_scene_file(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps({"width": 16, "height": 12}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path)])

    assert result.exit_code == 2

    def strip_ansi(text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)

    assert "Usage: render" in strip_ansi(result.stderr)


def _write_scene(path: Path) -> None:
    payload = {
        "width": 4,
        "height": 4,
        "frames": 2,
        "background": "#000000",
        "objects": [
            {
                "id": "square",
                "type": "rectangle",
                "color": "#ff0000",
                "position": [0, 0],
                "size": [2, 2],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_render_png_frames(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    output_dir = tmp_path / "png"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [str(scene_path), "--format", "png", "--output", str(output_dir)],
    )

    assert result.exit_code == 0
    contents = list(output_dir.glob("*.png"))
    assert len(contents) == Scene.from_dict(json.loads(scene_path.read_text())).frame_count


def test_render_gif_animation(tmp_path: Path) -> None:
    pytest.importorskip("PIL.Image")
    pytest.importorskip("imageio")

    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [str(scene_path), "--format", "gif", "--output", str(tmp_path / "animation")],
    )

    assert result.exit_code == 0
    destination = tmp_path / "animation.gif"
    assert destination.exists()
    assert destination.read_bytes().startswith(b"GIF89a")


def test_render_rejects_unknown_format(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path), "--format", "unknown"])

    assert result.exit_code == 2
    assert "format must be one of" in result.stderr
