from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.chopper.renderer import Frame, Renderer, Scene, SceneError, parse_color


def build_scene_dict() -> dict[str, object]:
    return {
        "width": 16,
        "height": 12,
        "frames": 4,
        "background": "#123456",
        "objects": [
            {
                "id": "background-strip",
                "type": "rectangle",
                "color": "#ff8800",
                "position": [2, 1],
                "size": [12, 4],
            },
            {
                "id": "hero",
                "type": "circle",
                "color": [32, 64, 255],
                "position": [2, 6],
                "size": [6, 6],
                "animation": [
                    {"frame": 0, "x": 2, "y": 6},
                    {"frame": 3, "x": 12, "y": 8},
                ],
            },
        ],
    }


def test_scene_from_dict_creates_objects() -> None:
    payload = build_scene_dict()
    scene = Scene.from_dict(payload)

    assert scene.width == 16
    assert scene.height == 12
    assert scene.frame_count == 4
    assert scene.background == (0x12, 0x34, 0x56)
    assert len(scene.objects) == 2
    assert scene.objects[0].kind == "rectangle"
    assert scene.objects[1].kind == "circle"


def test_parse_color_accepts_various_inputs() -> None:
    assert parse_color("#fff") == (255, 255, 255)
    assert parse_color("336699") == (0x33, 0x66, 0x99)
    assert parse_color((1, 2, 3)) == (1, 2, 3)

    with pytest.raises(SceneError):
        parse_color("#12")

    with pytest.raises(SceneError):
        parse_color((1, 2))


def test_renderer_produces_expected_frames(tmp_path: Path) -> None:
    scene = Scene.from_dict(build_scene_dict())
    renderer = Renderer(scene)

    frames = renderer.render()
    assert len(frames) == scene.frame_count

    first_frame = frames[0]
    assert first_frame.pixels[0][0] == scene.background
    assert first_frame.pixels[2][3] == (255, 136, 0)

    final_frame = frames[-1]
    assert final_frame.pixels[8][12] == (32, 64, 255)

    # Frames should be serialisable to bytes and to PPM files.
    encoded = first_frame.to_bytes()
    assert len(encoded) == scene.width * scene.height * 3

    destination = tmp_path / "frame_0000.ppm"
    first_frame.save_ppm(destination)
    contents = destination.read_text().splitlines()
    assert contents[0] == "P3"
    assert contents[1] == f"{scene.width} {scene.height}"
    assert contents[2] == "255"


def test_scene_serialisation_round_trip(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(json.dumps(build_scene_dict()), encoding="utf-8")

    scene = Scene.from_dict(json.loads(scene_path.read_text(encoding="utf-8")))
    renderer = Renderer(scene)

    frames = renderer.render()
    assert isinstance(frames[0], Frame)
    assert frames[0].pixels[1][2] == (255, 136, 0)


def test_scene_rejects_non_mapping_objects() -> None:
    payload: dict[str, Any] = build_scene_dict()
    payload["objects"] = [
        payload["objects"][0],
        "not-a-mapping",
    ]

    with pytest.raises(SceneError, match="index 1"):
        Scene.from_dict(payload)


@pytest.mark.parametrize(
    "animation_payload, expected_message",
    [
        (42, "iterable"),
        (["not-a-mapping"], "index 0"),
        ([{"x": 1.0}], "missing"),
    ],
)
def test_scene_object_rejects_invalid_animation(
    animation_payload: object, expected_message: str
) -> None:
    payload: dict[str, Any] = build_scene_dict()
    hero = payload["objects"][1]
    hero["animation"] = animation_payload

    with pytest.raises(SceneError, match=expected_message):
        Scene.from_dict(payload)
