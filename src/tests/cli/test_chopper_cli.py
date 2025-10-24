from __future__ import annotations

import json
import re
import importlib
from pathlib import Path

import pytest
from typer.testing import CliRunner
import typer

from apps.chopper.app import app
from apps.chopper.renderer import Scene

chopper_app_module = importlib.import_module("apps.chopper.app")
chopper_renderer_module = importlib.import_module("apps.chopper.renderer")

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def test_render_reports_invalid_scene_file(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps({"width": 16, "height": 12}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path)])

    assert result.exit_code == 2
    assert "Usage: render" in strip_ansi(result.stderr)


def test_render_reports_non_numeric_scene_width(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps({"width": "wide", "height": 12, "frames": 1}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path)])

    assert result.exit_code == 2
    message_lines = strip_ansi(result.stderr).splitlines()
    clean_text = " ".join(line.strip(" │") for line in message_lines)
    assert "Scene width must be an integer value" in clean_text
    assert "'wide'" in clean_text


def test_render_reports_malformed_scene_height(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps({"width": 12, "height": {"value": 4}, "frames": 1}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path)])

    assert result.exit_code == 2
    message_lines = strip_ansi(result.stderr).splitlines()
    clean_text = " ".join(line.strip(" │") for line in message_lines)
    assert "Scene height must be an integer value" in clean_text
    assert "{'value': 4}" in clean_text


def test_render_reports_non_numeric_frame_count(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps({"width": 12, "height": 8, "frames": "many"}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path)])

    assert result.exit_code == 2
    message_lines = strip_ansi(result.stderr).splitlines()
    clean_text = " ".join(line.strip(" │") for line in message_lines)
    assert "Scene frame count must be an integer value" in clean_text
    assert "'many'" in clean_text


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
    assert (
        len(contents) == Scene.from_dict(json.loads(scene_path.read_text())).frame_count
    )


def test_render_png_reports_missing_pillow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    def fake_require_pillow() -> None:
        raise RuntimeError(
            "Pillow is required for image export. Install the 'onepiece[chopper-images]' extra."
        )

    monkeypatch.setattr(
        chopper_renderer_module, "_require_pillow", fake_require_pillow, raising=True
    )

    output_dir = tmp_path / "png"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [str(scene_path), "--format", "png", "--output", str(output_dir)],
    )

    assert result.exit_code == 2
    message = strip_ansi(result.stderr)
    terms = ["Install", "the", "'onepiece[chopper-images]'", "extra"]
    for term in terms:
        assert term in message


def test_render_gif_animation(tmp_path: Path) -> None:
    pytest.importorskip("PIL.Image")
    pytest.importorskip("imageio")

    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [str(scene_path), "--output", str(tmp_path / "animation.gif")],
    )

    assert result.exit_code == 0
    destination = tmp_path / "animation.gif"
    assert destination.exists()
    assert destination.read_bytes().startswith(b"GIF89a")


def test_render_gif_reports_missing_pillow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    def fake_require_pillow() -> None:
        raise RuntimeError(
            "Pillow is required for image export. Install the 'onepiece[chopper-images]' extra."
        )

    monkeypatch.setattr(
        chopper_renderer_module, "_require_pillow", fake_require_pillow, raising=True
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [str(scene_path), "--output", str(tmp_path / "animation.gif")],
    )

    assert result.exit_code == 2
    message = strip_ansi(result.stderr)
    terms = ["Install", "the", "'onepiece[chopper-images]'", "extra"]
    for term in terms:
        assert term in message


def test_render_rejects_conflicting_suffix(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            str(scene_path),
            "--format",
            "gif",
            "--output",
            str(tmp_path / "animation.mp4"),
        ],
    )

    assert result.exit_code == 2
    terms = ["conflicts", "with", "format"]
    for term in terms:
        assert term in result.stderr


def test_render_rejects_unknown_format(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(app, [str(scene_path), "--format", "unknown"])

    assert result.exit_code == 2
    assert "format must be one of" in result.stderr


def test_render_mp4_reports_missing_animation_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    def fake_require_imageio() -> None:
        raise RuntimeError(
            "imageio is required for animation export. Install the 'onepiece[chopper-anim]' extra."
        )

    monkeypatch.setattr(
        chopper_renderer_module, "_require_imageio", fake_require_imageio, raising=True
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            str(scene_path),
            "--format",
            "mp4",
            "--output",
            str(tmp_path / "animation.mp4"),
        ],
    )

    assert result.exit_code == 2
    message = strip_ansi(result.stderr)
    terms = ["Install", "the", "'onepiece[chopper-anim]'", "extra"]
    for term in terms:
        assert term in message


def test_load_scene_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(typer.BadParameter, match="is a directory"):
        chopper_app_module._load_scene(tmp_path)


def test_load_scene_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text("{}", encoding="utf-8")

    def fake_read_text(self: Path, *, encoding: str = "utf-8") -> str:
        raise PermissionError("permission denied")

    monkeypatch.setattr(
        chopper_app_module.Path, "read_text", fake_read_text, raising=False
    )

    with pytest.raises(typer.BadParameter, match="cannot be read due to permissions"):
        chopper_app_module._load_scene(scene_path)


def test_load_scene_other_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text("{}", encoding="utf-8")

    def fake_read_text(self: Path, *, encoding: str = "utf-8") -> str:
        raise OSError("disk I/O error")

    monkeypatch.setattr(
        chopper_app_module.Path, "read_text", fake_read_text, raising=False
    )

    with pytest.raises(typer.BadParameter, match="could not be read: disk I/O error"):
        chopper_app_module._load_scene(scene_path)
