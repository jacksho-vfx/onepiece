from __future__ import annotations

import json
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import typing_extensions

from apps.chopper.renderer import (
    AnimationWriter,
    Frame,
    Renderer,
    Scene,
    SceneError,
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


def test_scene_object_rejects_unsupported_type(
    unsupported_scene_payload: dict[str, object],
) -> None:
    with pytest.raises(SceneError, match="Supported types are: rectangle, circle"):
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
    AnimationWriter(frames=frames, fps=12).write_gif(destination)

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

    writer = AnimationWriter(frames=frames, fps=24)
    writer.write_mp4(tmp_path / "animation.mp4")

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
