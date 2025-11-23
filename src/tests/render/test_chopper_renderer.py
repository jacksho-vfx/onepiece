from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import typing_extensions

from apps.chopper import renderer as renderer_module
from apps.chopper.renderer import (
    AnimationWriter,
    Color,
    GuidesOverlay,
    Frame,
    Renderer,
    Scene,
    SceneError,
    _blend_colors,
    parse_color,
)


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


def build_shape_scene() -> dict[str, object]:
    return {
        "width": 6,
        "height": 6,
        "frames": 1,
        "background": "#00000000",
        "objects": [
            {
                "id": "line",
                "type": "line",
                "color": "#00ff00",
                "position": [0, 0],
                "points": [[0, 5], [5, 5]],
                "stroke_width": 1,
            },
            {
                "id": "triangle",
                "type": "polygon",
                "color": "#0000ff",
                "stroke_color": "#ff00ff",
                "stroke_width": 1,
                "position": [0, 0],
                "points": [[1, 1], [4, 1], [4, 4], [1, 4]],
            },
        ],
    }


def build_stroked_shape_scene() -> dict[str, object]:
    return {
        "width": 8,
        "height": 8,
        "frames": 1,
        "background": "#00000000",
        "objects": [
            {
                "id": "panel",
                "type": "rectangle",
                "color": "#ffff00",
                "stroke_color": "#00ff00",
                "stroke_width": 1,
                "position": [1, 1],
                "size": [4, 3],
            },
            {
                "id": "badge",
                "type": "circle",
                "color": "#0000ff",
                "stroke_color": "#ffffff",
                "stroke_width": 2,
                "position": [5, 5],
                "size": [4, 4],
            },
        ],
    }


def build_rotated_shape_scene() -> dict[str, object]:
    return {
        "width": 5,
        "height": 5,
        "frames": 1,
        "background": "#00000000",
        "objects": [
            {
                "id": "rotated-rect",
                "type": "rectangle",
                "color": "#ff0000",
                "position": [2, 1],
                "size": [2, 1],
                "rotation": {"degrees": 90},
                "stroke_width": 0,
            },
            {
                "id": "rotated-line",
                "type": "line",
                "color": "#00ff00",
                "position": [3, 2],
                "points": [[0, 0], [2, 0]],
                "rotation": {"degrees": 90},
                "stroke_width": 1,
            },
        ],
    }


@pytest.fixture
def unsupported_scene_payload() -> dict[str, object]:
    payload = build_scene_dict()
    payload["objects"][0]["type"] = "triangle"  # type: ignore[index]
    return payload


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


def test_scene_accepts_unique_object_ids() -> None:
    payload = build_scene_dict()
    objects = cast(list[dict[str, object]], payload["objects"])
    objects.append(
        {
            "id": "backdrop",
            "type": "rectangle",
            "color": "#000000",
            "position": [0, 0],
            "size": [4, 3],
        }
    )

    scene = Scene.from_dict(payload)

    assert {obj.id for obj in scene.objects} == {
        "background-strip",
        "hero",
        "backdrop",
    }


def test_scene_rejects_duplicate_object_ids() -> None:
    payload = build_scene_dict()
    objects = cast(list[dict[str, object]], payload["objects"])
    duplicate = dict(objects[0])
    duplicate["id"] = str(objects[1]["id"])
    objects.append(duplicate)

    with pytest.raises(SceneError, match="duplicate id 'hero'"):
        Scene.from_dict(payload)


def test_scene_requires_mapping_payload() -> None:
    payload: Any = []

    with pytest.raises(SceneError, match="must be a mapping"):
        Scene.from_dict(payload)


def test_scene_object_requires_positive_size() -> None:
    payload = build_scene_dict()
    payload["objects"][0]["size"] = [0, 4]  # type: ignore[index]

    with pytest.raises(SceneError, match="positive width and height"):
        Scene.from_dict(payload)


def test_scene_object_requires_numeric_position_values() -> None:
    payload = build_scene_dict()
    payload["objects"][0]["position"] = ["left", 1]  # type: ignore[index]

    with pytest.raises(SceneError, match="numeric x and y"):
        Scene.from_dict(payload)


def test_scene_object_requires_finite_position_values() -> None:
    payload = build_scene_dict()
    payload["objects"][0]["position"] = [math.nan, 1.0]  # type: ignore[index]

    with pytest.raises(SceneError, match="finite numbers"):
        Scene.from_dict(payload)


def test_scene_object_parses_rotation_units() -> None:
    payload = build_scene_dict()
    payload["objects"][0]["rotation"] = {"degrees": 90}  # type: ignore[index]
    payload["objects"][1]["rotation"] = {"radians": math.pi}  # type: ignore[index]

    scene = Scene.from_dict(payload)

    assert scene.objects[0].rotation == pytest.approx(math.pi / 2)
    assert scene.objects[1].rotation == pytest.approx(math.pi)


def test_scene_object_rejects_invalid_easing() -> None:
    payload = build_scene_dict()
    payload["objects"][1]["easing"] = "squish"  # type: ignore[index]

    with pytest.raises(SceneError, match="Unsupported easing function"):
        Scene.from_dict(payload)


def test_scene_object_animation_requires_finite_coordinates() -> None:
    payload = build_scene_dict()
    payload["objects"][1]["animation"][0]["x"] = float("nan")  # type: ignore[index]

    with pytest.raises(SceneError, match="finite coordinate values"):
        Scene.from_dict(payload)


def test_scene_object_animation_requires_keyframes() -> None:
    payload = build_scene_dict()
    payload["objects"][1]["animation"] = []  # type: ignore[index]

    with pytest.raises(
        SceneError, match="animation must contain at least one keyframe"
    ):
        Scene.from_dict(payload)


def test_scene_object_animation_rejects_unsorted_keyframes() -> None:
    payload = build_scene_dict()
    objects = cast(list[dict[str, object]], payload["objects"])
    hero = objects[1]
    hero["animation"] = [
        {"frame": 3, "x": 12, "y": 8},
        {"frame": 0, "x": 2, "y": 6},
    ]

    with pytest.raises(SceneError, match="ordered by increasing frame"):
        Scene.from_dict(payload)


def test_scene_object_animation_rejects_duplicate_keyframes() -> None:
    payload = build_scene_dict()
    objects = cast(list[dict[str, object]], payload["objects"])
    hero = objects[1]
    hero["animation"] = [
        {"frame": 0, "x": 2, "y": 6},
        {"frame": 0, "x": 4, "y": 8},
    ]

    with pytest.raises(SceneError, match="unique frame numbers"):
        Scene.from_dict(payload)


def test_scene_object_rejects_unsupported_type(
    unsupported_scene_payload: dict[str, object],
) -> None:
    with pytest.raises(
        SceneError, match="Supported types are: rectangle, circle, line, polygon"
    ):
        Scene.from_dict(unsupported_scene_payload)


def test_circle_requires_positive_diameter() -> None:
    payload = build_scene_dict()
    payload["objects"][1]["size"] = [6, -1]  # type: ignore[index]

    with pytest.raises(SceneError, match="positive width and height"):
        Scene.from_dict(payload)


def test_parse_color_accepts_various_inputs() -> None:
    assert parse_color("#fff") == (255, 255, 255)
    assert parse_color("336699") == (0x33, 0x66, 0x99)
    assert parse_color((1, 2, 3)) == (1, 2, 3)
    assert parse_color("#11223344") == (0x11, 0x22, 0x33, 0x44)
    assert parse_color((1, 2, 3, 4)) == (1, 2, 3, 4)

    with pytest.raises(SceneError):
        parse_color("#12")

    with pytest.raises(SceneError):
        parse_color((1, 2))


def test_parse_color_rejects_out_of_range_components() -> None:
    with pytest.raises(SceneError, match="0-255"):
        parse_color((-1, 0, 0))

    with pytest.raises(SceneError, match="0-255"):
        parse_color((0, 0, 300))

    with pytest.raises(SceneError, match="0-255"):
        parse_color((0, 0, 0, 999))


def test_renderer_produces_expected_frames(tmp_path: Path) -> None:
    scene = Scene.from_dict(build_scene_dict())
    renderer = Renderer(scene)

    frames = list(renderer.render())
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


def test_scene_object_visibility_window() -> None:
    scene = Scene.from_dict(
        {
            "width": 2,
            "height": 1,
            "frames": 3,
            "background": "#000000",
            "objects": [
                {
                    "id": "flash",
                    "type": "rectangle",
                    "color": "#ffffff",
                    "position": [0, 0],
                    "size": [2, 1],
                    "start_frame": 1,
                    "end_frame": 1,
                }
            ],
        }
    )

    frames = list(Renderer(scene).render())

    assert all(pixel == (0, 0, 0) for pixel in frames[0].pixels[0])
    assert all(pixel == (255, 255, 255) for pixel in frames[1].pixels[0])
    assert all(pixel == (0, 0, 0) for pixel in frames[2].pixels[0])


def test_scene_object_visibility_keyframes() -> None:
    scene = Scene.from_dict(
        {
            "width": 2,
            "height": 1,
            "frames": 4,
            "background": "#000000",
            "objects": [
                {
                    "id": "blip",
                    "type": "rectangle",
                    "color": "#ff0000",
                    "position": [0, 0],
                    "size": [2, 1],
                    "visibility": [
                        {"frame": 0, "visible": True},
                        {"frame": 2, "visible": False},
                        {"frame": 3, "visible": True},
                    ],
                }
            ],
        }
    )

    frames = list(Renderer(scene).render())

    assert all(pixel == (255, 0, 0) for pixel in frames[0].pixels[0])
    assert all(pixel == (255, 0, 0) for pixel in frames[1].pixels[0])
    assert all(pixel == (0, 0, 0) for pixel in frames[2].pixels[0])
    assert all(pixel == (255, 0, 0) for pixel in frames[3].pixels[0])


def test_supersampling_smooths_diagonal_line() -> None:
    scene = Scene.from_dict(
        {
            "width": 2,
            "height": 2,
            "frames": 1,
            "background": "#00000000",
            "objects": [
                {
                    "id": "diag",
                    "type": "line",
                    "color": "#ff0000",
                    "position": [0, 0],
                    "points": [[0, 0], [1, 1]],
                    "stroke_width": 1,
                }
            ],
        }
    )

    base = next(Renderer(scene).render())
    supersampled = next(Renderer(scene, samples=4).render())

    assert base.pixels[0][1] == (0, 0, 0, 0)
    assert supersampled.pixels[0][1] == (143, 0, 0, 143)
    assert supersampled.pixels[1][0] == (143, 0, 0, 143)


def test_supersampling_softens_polygon_edges() -> None:
    scene = Scene.from_dict(
        {
            "width": 2,
            "height": 2,
            "frames": 1,
            "background": "#00000000",
            "objects": [
                {
                    "id": "poly",
                    "type": "polygon",
                    "color": "#0000ff",
                    "position": [0, 0],
                    "points": [
                        [0.5, 0.5],
                        [1.5, 0.5],
                        [1.5, 1.5],
                        [0.5, 1.5],
                    ],
                    "stroke_width": 0,
                }
            ],
        }
    )

    base = next(Renderer(scene).render())
    supersampled = next(Renderer(scene, samples=4).render())

    assert base.pixels[0][0] == (0, 0, 0, 0)
    assert supersampled.pixels[0][0] == (0, 0, 64, 64)
    assert supersampled.pixels[1][1] == (0, 0, 96, 96)


def test_gaussian_filter_downsamples_supersampled_frames() -> None:
    scene = Scene.from_dict(
        {
            "width": 2,
            "height": 2,
            "frames": 1,
            "background": "#00000000",
            "objects": [
                {
                    "id": "diag",
                    "type": "line",
                    "color": "#00ff00",
                    "position": [0, 0],
                    "points": [[0, 0], [1, 1]],
                    "stroke_width": 1,
                }
            ],
        }
    )

    frame = next(Renderer(scene, samples=2, filter_name="gaussian").render())

    assert frame.width == scene.width
    assert frame.height == scene.height
    assert frame.pixels[0][1][1] > 0


def test_renderer_blends_transparent_shapes_over_background() -> None:
    payload = {
        "width": 1,
        "height": 1,
        "frames": 1,
        "background": "#ff0000",
        "objects": [
            {
                "id": "overlay",
                "type": "rectangle",
                "color": (0, 0, 255, 128),
                "position": [0, 0],
                "size": [1, 1],
                "stroke_width": 0,
            }
        ],
    }

    scene = Scene.from_dict(payload)
    frame = next(Renderer(scene).render())

    assert frame.pixels[0][0] == (127, 0, 128, 255)


def test_renderer_stacks_multiple_transparent_shapes() -> None:
    payload = {
        "width": 1,
        "height": 1,
        "frames": 1,
        "background": "#ffffff",
        "objects": [
            {
                "id": "shadow",
                "type": "rectangle",
                "color": (0, 0, 0, 128),
                "position": [0, 0],
                "size": [1, 1],
                "stroke_width": 0,
            },
            {
                "id": "highlight",
                "type": "rectangle",
                "color": (255, 0, 0, 128),
                "position": [0, 0],
                "size": [1, 1],
                "stroke_width": 0,
            },
        ],
    }

    scene = Scene.from_dict(payload)
    frame = next(Renderer(scene).render())

    assert frame.pixels[0][0] == (191, 63, 63, 255)


def test_linear_gradient_rectangle() -> None:
    scene = Scene.from_dict(
        {
            "width": 2,
            "height": 1,
            "frames": 1,
            "background": "#00000000",
            "objects": [
                {
                    "id": "gradient",
                    "type": "rectangle",
                    "color": {
                        "type": "linear-gradient",
                        "from": [0, 0],
                        "to": [1, 0],
                        "colors": ["#ff0000", "#0000ff"],
                    },
                    "position": [0, 0],
                    "size": [2, 1],
                    "stroke_width": 0,
                }
            ],
        }
    )

    frame = next(Renderer(scene).render())

    assert frame.pixels[0][0] == (191, 0, 64, 255)
    assert frame.pixels[0][1] == (64, 0, 191, 255)


def test_radial_gradient_rectangle() -> None:
    scene = Scene.from_dict(
        {
            "width": 3,
            "height": 3,
            "frames": 1,
            "background": "#00000000",
            "objects": [
                {
                    "id": "spotlight",
                    "type": "rectangle",
                    "color": {
                        "type": "radial-gradient",
                        "center": [0.5, 0.5],
                        "radius": 0.5,
                        "colors": ["#ffffff", "#000000"],
                    },
                    "position": [0, 0],
                    "size": [3, 3],
                    "stroke_width": 0,
                }
            ],
        }
    )

    frame = next(Renderer(scene).render())

    assert frame.pixels[1][1] == (255, 255, 255, 255)
    assert frame.pixels[0][0][0] < 64


def test_textured_polygon(tmp_path: Path) -> None:
    pillow = pytest.importorskip("PIL.Image")
    texture = tmp_path / "texture.png"
    image = pillow.new("RGBA", (2, 2))
    image.putpixel((0, 0), (255, 0, 0, 255))
    image.putpixel((1, 0), (0, 255, 0, 255))
    image.putpixel((0, 1), (0, 0, 255, 255))
    image.putpixel((1, 1), (255, 255, 255, 255))
    image.save(texture)

    scene = Scene.from_dict(
        {
            "width": 2,
            "height": 2,
            "frames": 1,
            "background": "#00000000",
            "objects": [
                {
                    "id": "textured",
                    "type": "polygon",
                    "color": {"type": "texture", "path": str(texture)},
                    "position": [0, 0],
                    "points": [[0, 0], [2, 0], [2, 2], [0, 2]],
                    "stroke_width": 0,
                }
            ],
        }
    )

    frame = next(Renderer(scene).render())

    assert frame.pixels[0][0] == (255, 0, 0, 255)
    assert frame.pixels[1][1] == (255, 255, 255, 255)


def test_renderer_sorts_objects_by_z_index() -> None:
    payload = {
        "width": 1,
        "height": 1,
        "frames": 1,
        "background": "#00000000",
        "objects": [
            {
                "id": "foreground",
                "type": "rectangle",
                "color": "#ff0000",
                "position": [0, 0],
                "size": [1, 1],
                "z_index": 1,
            },
            {
                "id": "background",
                "type": "rectangle",
                "color": "#0000ff",
                "position": [0, 0],
                "size": [1, 1],
                "z_index": -1,
            },
        ],
    }

    scene = Scene.from_dict(payload)
    frame = next(Renderer(scene).render())

    assert frame.pixels[0][0] == (255, 0, 0, 255)


def test_renderer_preserves_order_with_equal_z_index() -> None:
    payload = {
        "width": 1,
        "height": 1,
        "frames": 1,
        "background": "#00000000",
        "objects": [
            {
                "id": "first",
                "type": "rectangle",
                "color": "#00ff00",
                "position": [0, 0],
                "size": [1, 1],
            },
            {
                "id": "second",
                "type": "rectangle",
                "color": "#0000ff",
                "position": [0, 0],
                "size": [1, 1],
            },
        ],
    }

    scene = Scene.from_dict(payload)
    frame = next(Renderer(scene).render())

    assert frame.pixels[0][0] == (0, 0, 255, 255)


def test_animation_easing_applied_to_positions() -> None:
    payload = {
        "width": 4,
        "height": 4,
        "frames": 3,
        "background": "#00000000",
        "objects": [
            {
                "id": "hero",
                "type": "circle",
                "color": "#ffffff",
                "position": [0, 0],
                "size": [2, 2],
                "easing": "ease-in",
                "animation": [
                    {"frame": 0, "x": 0, "y": 0},
                    {"frame": 2, "x": 10, "y": 0},
                ],
            }
        ],
    }

    scene = Scene.from_dict(payload)
    obj = scene.objects[0]

    halfway = obj.position_at(1)
    assert halfway[0] == pytest.approx(2.5)
    assert halfway[1] == pytest.approx(0.0)


def test_animation_interpolates_rotation() -> None:
    payload = {
        "width": 2,
        "height": 2,
        "frames": 3,
        "background": "#00000000",
        "objects": [
            {
                "id": "spinner",
                "type": "rectangle",
                "color": "#ffffff",
                "position": [0, 0],
                "size": [1, 1],
                "animation": [
                    {"frame": 0, "rotation": {"degrees": 0}},
                    {"frame": 2, "rotation": {"degrees": 90}},
                ],
            }
        ],
    }

    scene = Scene.from_dict(payload)
    obj = scene.objects[0]

    assert obj.rotation_at(0) == pytest.approx(0)
    assert obj.rotation_at(1) == pytest.approx(math.pi / 4)
    assert obj.rotation_at(2) == pytest.approx(math.pi / 2)


def test_animation_interpolates_color_channels() -> None:
    payload = {
        "width": 1,
        "height": 1,
        "frames": 3,
        "background": "#000000",
        "objects": [
            {
                "id": "panel",
                "type": "rectangle",
                "color": "#ff0000",
                "position": [0, 0],
                "size": [1, 1],
                "stroke_width": 0,
                "animation": [
                    {"frame": 0, "color": "#ff0000"},
                    {"frame": 2, "color": "#0000ff"},
                ],
            }
        ],
    }

    scene = Scene.from_dict(payload)
    frames = list(Renderer(scene).render())

    assert frames[0].pixels[0][0] == (255, 0, 0)
    assert frames[1].pixels[0][0] == (128, 0, 128)
    assert frames[2].pixels[0][0] == (0, 0, 255)


def test_animation_interpolates_alpha_channel() -> None:
    payload = {
        "width": 1,
        "height": 1,
        "frames": 3,
        "background": "#00000000",
        "objects": [
            {
                "id": "panel",
                "type": "rectangle",
                "color": "#ff0000ff",
                "position": [0, 0],
                "size": [1, 1],
                "stroke_width": 0,
                "animation": [
                    {"frame": 0, "color": "#ff0000ff"},
                    {"frame": 2, "color": "#ff000000"},
                ],
            }
        ],
    }

    scene = Scene.from_dict(payload)
    frames = list(Renderer(scene).render())

    assert frames[0].pixels[0][0] == (255, 0, 0, 255)
    assert frames[1].pixels[0][0] == (255, 0, 0, 128)
    assert frames[2].pixels[0][0] == (0, 0, 0, 0)


def test_animation_keyframe_easing_overrides_default() -> None:
    payload = {
        "width": 4,
        "height": 4,
        "frames": 3,
        "background": "#000000",
        "objects": [
            {
                "id": "hero",
                "type": "circle",
                "color": "#ffffff",
                "position": [0, 0],
                "size": [2, 2],
                "easing": "ease-in",
                "animation": [
                    {"frame": 0, "x": 0, "y": 0, "easing": "ease-out"},
                    {"frame": 2, "x": 10, "y": 0},
                ],
            }
        ],
    }

    scene = Scene.from_dict(payload)
    obj = scene.objects[0]

    halfway = obj.position_at(1)
    assert halfway[0] == pytest.approx(7.5)
    assert halfway[1] == pytest.approx(0.0)


def test_animation_supports_cubic_easing() -> None:
    payload = {
        "width": 4,
        "height": 4,
        "frames": 3,
        "background": "#000000",
        "objects": [
            {
                "id": "hero",
                "type": "circle",
                "color": "#ffffff",
                "position": [0, 0],
                "size": [2, 2],
                "easing": "cubic(0,0,1,1)",
                "animation": [
                    {"frame": 0, "x": 0, "y": 0},
                    {"frame": 2, "x": 10, "y": 0},
                ],
            }
        ],
    }

    scene = Scene.from_dict(payload)
    obj = scene.objects[0]

    halfway = obj.position_at(1)
    assert halfway[0] == pytest.approx(5.0)
    assert halfway[1] == pytest.approx(0.0)


class _NoopObject:
    def __init__(self) -> None:
        self.rendered_frames: list[int] = []

    def render(self, frame: Frame, index: int, scale: int = 1) -> None:
        frame.pixels[0][0] = (index, 0, 0)
        self.rendered_frames.append(index)


def test_parallel_render_preserves_order_with_workers() -> None:
    scene = Scene(width=1, height=1, frame_count=4, background=(0, 0, 0), objects=[])
    worker = _NoopObject()
    scene.objects = [worker]

    renderer = Renderer(scene)
    frames = list(renderer.render(workers=2, backend="thread"))

    assert [frame.index for frame in frames] == [0, 1, 2, 3]
    assert [frame.pixels[0][0][:3] for frame in frames] == [
        (0, 0, 0),
        (1, 0, 0),
        (2, 0, 0),
        (3, 0, 0),
    ]
    assert sorted(worker.rendered_frames) == [0, 1, 2, 3]


def test_parallel_render_reduces_wall_time(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = Scene(width=1, height=1, frame_count=4, background=(0, 0, 0), objects=[])
    scene.objects = [_NoopObject()]

    original_render = renderer_module._render_frame_static

    def slow_render(
        scene: Scene, index: int, samples: int, filter_name: str, guides: None
    ) -> Frame:
        time.sleep(0.05)
        return original_render(scene, index, samples, filter_name, guides)

    monkeypatch.setattr(renderer_module, "_render_frame_static", slow_render)

    renderer = Renderer(scene)

    start = time.perf_counter()
    list(renderer.render())
    sequential_duration = time.perf_counter() - start

    start = time.perf_counter()
    list(renderer.render(workers=4, backend="thread"))
    parallel_duration = time.perf_counter() - start

    assert parallel_duration < sequential_duration
    assert parallel_duration < sequential_duration * 0.8


def test_line_and_polygon_rendering() -> None:
    scene = Scene.from_dict(build_shape_scene())
    renderer = Renderer(scene)

    frame = next(renderer.render())

    # Polygon fill and stroke
    assert frame.pixels[2][2] == (0, 0, 255, 255)
    assert frame.pixels[1][1] == (255, 0, 255, 255)
    assert frame.pixels[0][0] == (0, 0, 0, 0)

    # Line stroke across the bottom row
    for x in range(scene.width):
        assert frame.pixels[5][x] == (0, 255, 0, 255)


def test_rectangle_and_circle_strokes() -> None:
    scene = Scene.from_dict(build_stroked_shape_scene())
    renderer = Renderer(scene)

    frame = next(renderer.render())

    # Rectangle stroke and fill
    assert frame.pixels[1][1] == (0, 255, 0, 255)
    assert frame.pixels[2][2] == (255, 255, 0, 255)

    # Circle stroke and fill
    assert frame.pixels[5][5] == (0, 0, 255, 255)
    assert frame.pixels[5][7] == (255, 255, 255, 255)


def test_rotated_shapes_render_correctly() -> None:
    scene = Scene.from_dict(build_rotated_shape_scene())
    renderer = Renderer(scene)

    frame = next(renderer.render())

    # Rotated rectangle occupies two rows after 90 degree rotation about its origin
    assert frame.pixels[1][1] == (255, 0, 0, 255)
    assert frame.pixels[2][1] == (255, 0, 0, 255)
    assert frame.pixels[1][2] == (255, 0, 0, 255)
    assert frame.pixels[2][2] == (255, 0, 0, 255)

    # Rotated line now vertical at x=3
    assert frame.pixels[2][3] == (0, 255, 0, 255)
    assert frame.pixels[3][3] == (0, 255, 0, 255)
    assert frame.pixels[4][3] == (0, 255, 0, 255)


def test_guides_overlay_draws_over_scene_objects() -> None:
    scene = Scene.from_dict(
        {
            "width": 3,
            "height": 3,
            "frames": 1,
            "background": "#000000",
            "objects": [
                {
                    "id": "fill",
                    "type": "rectangle",
                    "color": "#ff0000",
                    "position": [0, 0],
                    "size": [3, 3],
                    "stroke_width": 0,
                }
            ],
        }
    )

    guides = GuidesOverlay(
        thirds_grid=True,
        center_mark=True,
        color=(0, 255, 0),
        opacity=1.0,
        stroke_width=1.0,
    )
    frame = next(Renderer(scene, guides=guides).render())

    assert frame.pixels == [
        [(255, 0, 0), (0, 255, 0, 255), (0, 255, 0, 255)],
        [(0, 255, 0, 255), (0, 255, 0, 255), (0, 255, 0, 255)],
        [(0, 255, 0, 255), (0, 255, 0, 255), (0, 255, 0, 255)],
    ]


def test_guides_overlay_respects_opacity() -> None:
    scene = Scene(width=5, height=5, frame_count=1, background=(0, 0, 0, 0), objects=[])
    guides = GuidesOverlay(center_mark=True, color=(255, 255, 255), opacity=0.25)

    frame = next(Renderer(scene, guides=guides).render())
    assert frame.pixels[2][2] == (255, 255, 255, 112)


def test_guides_overlay_scales_with_supersampling() -> None:
    scene = Scene(width=2, height=2, frame_count=1, background=(0, 0, 0), objects=[])
    guides = GuidesOverlay(action_frame=True, color=(0, 0, 255), opacity=1.0)

    frame = next(Renderer(scene, samples=2, guides=guides).render())

    assert frame.pixels[0][0] == (0, 0, 255, 255)
    assert frame.pixels[-1][-1] == (0, 0, 255, 255)


def test_line_requires_two_points() -> None:
    payload = build_shape_scene()
    payload["objects"][0]["points"] = [[0, 0]]  # type: ignore[index]

    with pytest.raises(SceneError, match="must contain exactly 2 point"):
        Scene.from_dict(payload)


def test_line_rejects_excess_points() -> None:
    payload = build_shape_scene()
    payload["objects"][0]["points"] = [[0, 0], [1, 1], [2, 2]]  # type: ignore[index]

    with pytest.raises(SceneError, match="must contain exactly 2 point"):
        Scene.from_dict(payload)


def test_polygon_requires_three_points() -> None:
    payload = build_shape_scene()
    payload["objects"][1]["points"] = [[0, 0], [1, 1]]  # type: ignore[index]

    with pytest.raises(SceneError, match="must contain at least 3 point"):
        Scene.from_dict(payload)


def test_line_rejects_non_positive_stroke_width() -> None:
    payload = build_shape_scene()
    payload["objects"][0]["stroke_width"] = 0  # type: ignore[index]

    with pytest.raises(SceneError, match="stroke width must be greater than zero"):
        Scene.from_dict(payload)


def test_renderer_render_is_iterator() -> None:
    scene = Scene.from_dict(build_scene_dict())
    renderer = Renderer(scene)

    frames_iter = renderer.render()
    assert isinstance(frames_iter, Iterator)

    first_frame = next(frames_iter)
    assert first_frame.index == 0

    remaining = list(frames_iter)
    assert len(remaining) == scene.frame_count - 1
    assert remaining[-1].index == scene.frame_count - 1


def test_frame_png_export_preserves_alpha(tmp_path: Path) -> None:
    pytest.importorskip("PIL.Image")

    frame = Frame(
        index=0,
        width=2,
        height=1,
        pixels=[[(255, 0, 0, 128), (0, 0, 255, 255)]],
    )

    path = tmp_path / "frame.png"
    frame.save_png(path)

    contents = path.read_bytes()
    assert contents.startswith(b"\x89PNG\r\n\x1a\n")

    from PIL import Image

    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.size == (2, 1)
        assert image.getpixel((0, 0)) == (255, 0, 0, 128)
        assert image.getpixel((1, 0)) == (0, 0, 255, 255)


def test_frame_to_image_rgb_matches_bytes() -> None:
    pytest.importorskip("PIL.Image")

    frame = Frame(
        index=0,
        width=2,
        height=1,
        pixels=[[(255, 0, 0), (0, 255, 0)]],
    )

    image = frame.to_image()

    assert image.mode == "RGB"
    assert image.size == (2, 1)
    assert image.tobytes() == frame.to_bytes()


def test_frame_to_image_rgba_matches_bytes() -> None:
    pytest.importorskip("PIL.Image")

    frame = Frame(
        index=0,
        width=2,
        height=1,
        pixels=[[(255, 0, 0, 128), (0, 0, 255, 255)]],
    )

    image = frame.to_image()

    assert image.mode == "RGBA"
    assert image.size == (2, 1)
    assert image.tobytes() == frame.to_bytes(mode="RGBA")


def test_blend_colors_preserves_alpha_when_opaque() -> None:
    opaque_gray = _blend_colors((255, 255, 255, 255), (0, 0, 0, 128))

    assert opaque_gray == (127, 127, 127, 255)


def test_frame_alpha_tracking_updates_during_blends() -> None:
    frame = Frame(index=0, width=1, height=1, pixels=[[(0, 0, 0, 0)]], has_alpha=False)

    assert frame.has_alpha is False

    row = frame.pixels[0]
    frame._blend_into(row, 0, (255, 0, 0, 128))

    assert frame.has_alpha is True


def test_frame_blending_retains_alpha_metadata_after_multiple_passes() -> None:
    frame = Frame(index=0, width=1, height=1, pixels=[[(0, 0, 0, 0)]], has_alpha=False)

    first_row = frame.pixels[0]
    frame._blend_into(first_row, 0, (255, 0, 0, 128))
    assert len(first_row[0]) == 4
    assert frame.has_alpha is True

    frame._blend_into(first_row, 0, (0, 255, 0, 255))

    assert len(first_row[0]) == 4
    assert first_row[0][3] == 255

    frame.has_alpha = None

    assert frame._has_alpha() is True


def test_frame_alpha_cache_avoids_expensive_scan() -> None:
    frame = Frame.blank(index=0, width=4, height=4, color=(0, 0, 0))

    class CountingPixels(list[list[Color]]):
        def __init__(self, rows: list[list[Color]]):
            super().__init__(rows)
            self.iterations = 0

        def __iter__(self) -> Iterator[list[Color]]:  # type: ignore[override]
            self.iterations += 1
            return super().__iter__()

    counted_pixels = CountingPixels(frame.pixels)
    frame.pixels = counted_pixels

    assert frame._has_alpha() is False
    assert counted_pixels.iterations == 0


def test_animation_writer_creates_gif(tmp_path: Path) -> None:
    pytest.importorskip("PIL.Image")
    pytest.importorskip("imageio")

    frames = [
        Frame(
            index=idx, width=1, height=1, pixels=[[(idx * 20, 0, 255 - idx * 20, 255)]]
        )
        for idx in range(3)
    ]

    destination = tmp_path / "animation.gif"
    frame_count = AnimationWriter(frames=iter(frames), fps=12).write_gif(destination)

    assert frame_count == len(frames)

    data = destination.read_bytes()
    assert data.startswith(b"GIF89a")

    from PIL import Image

    with Image.open(destination) as image:
        assert image.n_frames == len(frames)
        image.seek(0)
        first = image.convert("RGBA")
        assert first.getpixel((0, 0))[2] == 255
        image.seek(1)
        second = image.convert("RGBA")
        assert second.getpixel((0, 0))[0] == 20


def test_animation_writer_converts_frames_to_numpy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("PIL.Image")
    numpy = pytest.importorskip("numpy")

    frames = [
        Frame(index=0, width=1, height=1, pixels=[[(12, 34, 56)]]),
        Frame(index=1, width=1, height=1, pixels=[[(78, 90, 123)]]),
    ]

    class DummyStream:
        def __init__(self) -> None:
            self.captured: list[object] = []

        def append_data(self, data: object) -> None:
            self.captured.append(data)

    stream = DummyStream()

    class DummyModule:
        def get_writer(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            stream.captured.clear()

            class _Manager:
                def __enter__(self_inner) -> DummyStream:
                    return stream

                def __exit__(
                    self_inner,
                    exc_type: type[BaseException] | None,
                    exc: BaseException | None,
                    tb: object,
                ) -> typing_extensions.Literal[False]:
                    return False

            return _Manager()

    monkeypatch.setattr("apps.chopper.renderer._require_imageio", lambda: DummyModule())

    writer = AnimationWriter(frames=iter(frames), fps=24)
    frame_count = writer.write_mp4(tmp_path / "animation.mp4")

    assert frame_count == len(frames)
    assert len(stream.captured) == len(frames)
    for frame, data in zip(frames, stream.captured, strict=True):
        assert isinstance(data, numpy.ndarray)
        assert data.shape == (frame.height, frame.width, 3)
        assert data.dtype == numpy.uint8
        assert tuple(int(value) for value in data[0, 0]) == frame.pixels[0][0]


def test_scene_serialisation_round_trip(tmp_path: Path) -> None:
    scene_path = tmp_path / "scene.json"
    scene_path.write_text(json.dumps(build_scene_dict()), encoding="utf-8")

    scene = Scene.from_dict(json.loads(scene_path.read_text(encoding="utf-8")))
    renderer = Renderer(scene)

    frames = list(renderer.render())
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
    "field,value,expected_message",
    [
        ("width", 0, "width must be greater than zero"),
        ("width", -8, "width must be greater than zero"),
        ("height", 0, "height must be greater than zero"),
        ("height", -3, "height must be greater than zero"),
        ("frames", 0, "frame count must be greater than zero"),
        ("frames", -1, "frame count must be greater than zero"),
    ],
)
def test_scene_rejects_non_positive_dimensions(
    field: str, value: int, expected_message: str
) -> None:
    payload = build_scene_dict()
    payload[field] = value

    with pytest.raises(SceneError, match=expected_message):
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
