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
    result = runner.invoke(app, ["render", str(scene_path)])

    assert result.exit_code == 2
    assert "Usage: root render" in strip_ansi(result.stderr)


def test_render_reports_non_numeric_scene_width(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps({"width": "wide", "height": 12, "frames": 1}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["render", str(scene_path)])

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
    result = runner.invoke(app, ["render", str(scene_path)])

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
    result = runner.invoke(app, ["render", str(scene_path)])

    assert result.exit_code == 2
    message_lines = strip_ansi(result.stderr).splitlines()
    clean_text = " ".join(line.strip(" │") for line in message_lines)
    assert "Scene frame count must be an integer value" in clean_text
    assert "'many'" in clean_text


def test_inspect_reports_scene_summary(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene_with_animation(scene_path)

    runner = CliRunner()
    result = runner.invoke(app, ["inspect", str(scene_path)])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert "Dimensions: 8x6" in lines
    assert "Frames: 5" in lines
    assert "- mover (rectangle)" in lines
    assert "- static (circle)" in lines
    assert "- mover: frames 0-4 (2 keyframe(s))" in lines


def test_inspect_rejects_invalid_scene(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps({"width": 4, "height": 4, "frames": 0}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["inspect", str(scene_path)])

    assert result.exit_code == 2
    message_lines = strip_ansi(result.stderr).splitlines()
    clean_text = " ".join(line.strip(" │") for line in message_lines)
    assert "frame count must be greater than zero" in clean_text


def test_inspect_rejects_unsorted_animation_keyframes(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps(
            {
                "width": 4,
                "height": 4,
                "frames": 2,
                "objects": [
                    {
                        "id": "traveller",
                        "type": "rectangle",
                        "color": "#00ff00",
                        "position": [0, 0],
                        "size": [2, 2],
                        "animation": [
                            {"frame": 2, "x": 1, "y": 1},
                            {"frame": 1, "x": 0, "y": 0},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["inspect", str(scene_path)])

    assert result.exit_code == 2
    clean_text = " ".join(strip_ansi(result.stderr).split())
    assert "ordered by increasing frame" in clean_text


def test_inspect_rejects_duplicate_animation_keyframes(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps(
            {
                "width": 4,
                "height": 4,
                "frames": 2,
                "objects": [
                    {
                        "id": "traveller",
                        "type": "rectangle",
                        "color": "#00ff00",
                        "position": [0, 0],
                        "size": [2, 2],
                        "animation": [
                            {"frame": 1, "x": 1, "y": 1},
                            {"frame": 1, "x": 2, "y": 2},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["inspect", str(scene_path)])

    assert result.exit_code == 2
    clean_text = " ".join(strip_ansi(result.stderr).split())
    assert "unique frame numbers" in clean_text


def test_inspect_rejects_duplicate_object_ids(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(
        json.dumps(
            {
                "width": 4,
                "height": 4,
                "frames": 2,
                "objects": [
                    {
                        "id": "dupe",
                        "type": "rectangle",
                        "color": "#00ff00",
                        "position": [0, 0],
                        "size": [2, 2],
                    },
                    {
                        "id": "dupe",
                        "type": "circle",
                        "color": "#ff0000",
                        "position": [1, 1],
                        "size": [1, 1],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, ["inspect", str(scene_path)])

    assert result.exit_code == 2
    message_lines = strip_ansi(result.stderr).splitlines()
    clean_text = " ".join(line.strip(" │") for line in message_lines)
    assert "duplicate id 'dupe'" in clean_text


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
            },
            {
                "id": "path",
                "type": "line",
                "color": "#00ff00",
                "position": [0, 0],
                "points": [[0, 3], [3, 3]],
                "stroke_width": 1,
            },
            {
                "id": "triangle",
                "type": "polygon",
                "color": "#0000ff",
                "stroke_color": "#ffffff",
                "position": [0, 0],
                "points": [[0, 0], [3, 1], [1, 3]],
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_scene_with_animation(path: Path) -> None:
    payload = {
        "width": 8,
        "height": 6,
        "frames": 5,
        "objects": [
            {
                "id": "mover",
                "type": "rectangle",
                "color": "#123456",
                "position": [0, 0],
                "size": [2, 2],
                "animation": [
                    {"frame": 0, "x": 0, "y": 0},
                    {"frame": 4, "x": 2.5, "y": 1.5},
                ],
            },
            {
                "id": "static",
                "type": "circle",
                "color": "#654321",
                "position": [1, 1],
                "size": [1, 1],
            },
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
        ["render", str(scene_path), "--format", "png", "--output", str(output_dir)],
    )

    assert result.exit_code == 0
    contents = list(output_dir.glob("*.png"))
    assert (
        len(contents) == Scene.from_dict(json.loads(scene_path.read_text())).frame_count
    )


def test_render_supports_frame_range(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene_with_animation(scene_path)

    output_dir = tmp_path / "range"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--format",
            "png",
            "--output",
            str(output_dir),
            "--start",
            "1",
            "--end",
            "3",
        ],
    )

    assert result.exit_code == 0
    contents = sorted(output_dir.glob("*.png"))
    assert [path.name for path in contents] == [
        "frame_0001.png",
        "frame_0002.png",
        "frame_0003.png",
    ]
    assert "frames 1-3" in result.stdout


def test_render_supports_frame_list(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene_with_animation(scene_path)

    output_dir = tmp_path / "frames"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--format",
            "png",
            "--output",
            str(output_dir),
            "--frames",
            "2,0",
        ],
    )

    assert result.exit_code == 0
    contents = list(output_dir.glob("*.png"))
    assert [path.name for path in sorted(contents)] == [
        "frame_0000.png",
        "frame_0002.png",
    ]
    assert "frames 0, 2" in result.stdout


def test_render_rejects_invalid_frame_selection(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--start",
            "5",
        ],
    )

    assert result.exit_code == 2
    clean_text = " ".join(strip_ansi(result.stderr).split())
    assert "within the 0-1 range" in clean_text

    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--frames",
            "0,a",
        ],
    )

    assert result.exit_code == 2
    clean_text = " ".join(strip_ansi(result.stderr).split())
    assert "Frame value 'a' is not an integer" in clean_text

    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--frames",
            "0,1",
            "--start",
            "0",
        ],
    )

    assert result.exit_code == 2
    clean_text = " ".join(strip_ansi(result.stderr).split())
    assert "Cannot combine --frames with --start/--end options" in clean_text


def test_render_supports_background_override(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_blank_scene(scene_path)

    output_dir = tmp_path / "ppm"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--background",
            "#112233",
            "--output",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0
    ppm_path = output_dir / "frame_0000.ppm"
    assert ppm_path.exists()
    ppm_contents = ppm_path.read_text(encoding="ascii").splitlines()
    assert "17 34 51 17 34 51" in ppm_contents


def test_render_accepts_supersampling_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene_path = tmp_path / "scene.json"
    _write_blank_scene(scene_path)

    captured: dict[str, object] = {}

    def fake_render_scene(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(chopper_app_module, "render_scene", fake_render_scene)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--samples",
            "4",
            "--filter",
            "gaussian",
            "--workers",
            "3",
            "--worker-backend",
            "thread",
        ],
    )

    assert result.exit_code == 0
    assert captured["samples"] == 4
    assert captured["filter_name"] == "gaussian"
    assert captured["workers"] == 3
    assert captured["worker_backend"] == "thread"
    assert captured["guides"] is None


def test_render_accepts_guides_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene_path = tmp_path / "scene.json"
    _write_blank_scene(scene_path)

    captured: dict[str, object] = {}

    def fake_render_scene(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(chopper_app_module, "render_scene", fake_render_scene)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--safe-frame",
            "--thirds-grid",
            "--center-mark",
            "--guides-color",
            "#112233",
            "--guides-opacity",
            "0.75",
            "--guides-width",
            "2",
        ],
    )

    assert result.exit_code == 0
    guides = captured["guides"]
    assert isinstance(guides, chopper_renderer_module.GuidesOverlay)
    assert guides.safe_frame is True
    assert guides.action_frame is False
    assert guides.thirds_grid is True
    assert guides.center_mark is True
    assert guides.color == (0x11, 0x22, 0x33)
    assert guides.opacity == 0.75
    assert guides.stroke_width == 2


def test_render_rejects_invalid_background_override(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_blank_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app, ["render", str(scene_path), "--background", "not-a-colour"]
    )

    assert result.exit_code == 2
    assert "Could not parse colour value" in strip_ansi(result.stderr)


def test_render_rejects_invalid_guides(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_blank_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--safe-frame",
            "--guides-opacity",
            "1.5",
        ],
    )

    assert result.exit_code == 2
    assert "guides-opacity" in strip_ansi(result.stderr)


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
        ["render", str(scene_path), "--format", "png", "--output", str(output_dir)],
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
        ["render", str(scene_path), "--output", str(tmp_path / "animation.gif")],
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
        ["render", str(scene_path), "--output", str(tmp_path / "animation.gif")],
    )

    assert result.exit_code == 2
    message = strip_ansi(result.stderr)
    terms = ["Install", "the", "'onepiece[chopper-images]'", "extra"]
    for term in terms:
        assert term in message


@pytest.mark.parametrize("fps", [0, -12])
def test_render_gif_rejects_invalid_fps(tmp_path: Path, fps: int) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--output",
            str(tmp_path / "animation.gif"),
            "--fps",
            str(fps),
        ],
    )

    assert result.exit_code == 2
    message_lines = strip_ansi(result.stderr).splitlines()
    clean_text = " ".join(line.strip(" │") for line in message_lines)
    assert "Frames per second must be greater than zero" in clean_text


def test_render_rejects_conflicting_suffix(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "render",
            str(scene_path),
            "--format",
            "gif",
            "--output",
            str(tmp_path / "animation.mp4"),
        ],
    )

    assert result.exit_code == 2
    terms = ["conflicts", "with", "format"]
    clean_text = " ".join(strip_ansi(result.stderr).split())
    for term in terms:
        assert term in clean_text


def test_render_rejects_unknown_format(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    _write_scene(scene_path)

    runner = CliRunner()
    result = runner.invoke(app, ["render", str(scene_path), "--format", "unknown"])

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
            "render",
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


def _write_blank_scene(path: Path) -> None:
    payload = {"width": 2, "height": 1, "frames": 1, "objects": []}
    path.write_text(json.dumps(payload), encoding="utf-8")
