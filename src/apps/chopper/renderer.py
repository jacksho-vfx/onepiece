"""Lightweight scene renderer used by the Chopper application."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:  # pragma: no cover - dependency optional for basic functionality
    from PIL import Image as PILImage
except ImportError:  # pragma: no cover - handled lazily when export attempted
    PILImage = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import imageio.v3 as iio
    import numpy as np
else:
    try:
        import imageio.v3 as iio
    except ImportError:
        iio = None  # type: ignore[assignment]

    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]

Color = tuple[int, int, int] | tuple[int, int, int, int] | tuple[int, ...]


def _require_pillow() -> Any:
    """Return :mod:`PIL.Image` or raise a helpful error if unavailable."""

    if PILImage is None:
        raise RuntimeError(
            "Pillow is required for image export. Install the 'onepiece[chopper-images]' extra."
        )
    return PILImage


def _require_imageio() -> Any:
    """Return the :mod:`imageio.v3` module or raise a helpful error."""

    if iio is None:  # pragma: no cover - exercised in integration tests
        raise RuntimeError(
            "imageio is required for animation export. Install the 'onepiece[chopper-anim]' extra."
        )
    return iio


def _require_numpy() -> Any:
    """Return :mod:`numpy` or raise a helpful error if unavailable."""

    if np is None:
        raise RuntimeError(
            "NumPy is required for animation export. Install the 'onepiece[chopper-anim]' extra."
        )
    return np


class SceneError(ValueError):
    """Raised when a scene description is malformed."""


@dataclass(slots=True)
class Keyframe:
    """Represents a single keyframe in an animation track."""

    frame: int
    x: float
    y: float


@dataclass(slots=True)
class Animation:
    """Simple linear animation track for two-dimensional positions."""

    keyframes: list[Keyframe]

    def position_at(self, frame: int) -> tuple[float, float]:
        """Return the interpolated position for ``frame``."""

        if not self.keyframes:
            raise SceneError("Animation track defined without any keyframes")

        if frame <= self.keyframes[0].frame:
            start = self.keyframes[0]
            return start.x, start.y

        if frame >= self.keyframes[-1].frame:
            end = self.keyframes[-1]
            return end.x, end.y

        for left, right in pairwise(self.keyframes):
            if left.frame <= frame <= right.frame:
                if right.frame == left.frame:
                    return left.x, left.y
                t = (frame - left.frame) / (right.frame - left.frame)
                x = left.x + (right.x - left.x) * t
                y = left.y + (right.y - left.y) * t
                return x, y

        end = self.keyframes[-1]
        return end.x, end.y


def pairwise(values: Iterable[Keyframe]) -> Iterator[tuple[Keyframe, Keyframe]]:
    """Yield the values in ``values`` two at a time."""

    it = iter(values)
    prev = next(it)
    for current in it:
        yield prev, current
        prev = current


SUPPORTED_OBJECT_TYPES: tuple[str, ...] = ("rectangle", "circle")


@dataclass(slots=True)
class SceneObject:
    """Renderable object within a scene."""

    id: str
    kind: str
    color: Color
    position: tuple[float, float]
    size: tuple[float, float]
    animation: Animation | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "SceneObject":
        """Create an object from a dictionary description."""

        required = {"id", "type", "color", "position"}
        missing = required - payload.keys()
        if missing:
            joined = ", ".join(sorted(missing))
            raise SceneError(f"Scene object is missing required key(s): {joined}")

        kind = str(payload["type"])
        if kind not in SUPPORTED_OBJECT_TYPES:
            supported = ", ".join(SUPPORTED_OBJECT_TYPES)
            raise SceneError(
                f"Unsupported object type: {kind!r}. Supported types are: {supported}"
            )

        color = parse_color(payload["color"])

        position_data = payload["position"]
        if not isinstance(position_data, Sequence) or len(position_data) != 2:
            raise SceneError("Object position must be a length two sequence")
        position = float(position_data[0]), float(position_data[1])

        size_data = payload.get("size", (0, 0))
        if not isinstance(size_data, Sequence) or len(size_data) != 2:
            raise SceneError("Object size must be a length two sequence")
        try:
            width = float(size_data[0])
            height = float(size_data[1])
        except (TypeError, ValueError) as exc:
            raise SceneError(
                "Object size must contain numeric width and height values"
            ) from exc

        if not math.isfinite(width) or not math.isfinite(height):
            raise SceneError("Object size width and height must be finite numbers")

        if width <= 0 or height <= 0:
            raise SceneError(
                f"Object size must have positive width and height (got {width}x{height})"
            )

        size = width, height

        animation_data = payload.get("animation")
        animation = None
        if animation_data is not None:
            if not isinstance(animation_data, Iterable):
                raise SceneError("Object animation must be an iterable of mappings")

            keyframes: list[Keyframe] = []
            for index, item in enumerate(animation_data):
                if not isinstance(item, Mapping):
                    raise SceneError(
                        f"Object animation entry at index {index} must be a mapping"
                    )
                if "frame" not in item:
                    raise SceneError(
                        f"Object animation entry at index {index} is missing a 'frame' value"
                    )

                try:
                    frame_value = item["frame"]
                    frame = int(frame_value)
                except (TypeError, ValueError) as exc:
                    raise SceneError(
                        f"Object animation entry at index {index} has an invalid frame value: {item['frame']!r}"
                    ) from exc

                try:
                    x = float(item.get("x", position[0]))
                    y = float(item.get("y", position[1]))
                except (TypeError, ValueError) as exc:
                    raise SceneError(
                        f"Object animation entry at index {index} has invalid coordinate values"
                    ) from exc

                keyframes.append(Keyframe(frame=frame, x=x, y=y))

            keyframes.sort(key=lambda keyframe: keyframe.frame)
            animation = Animation(keyframes=keyframes)

        return cls(
            id=str(payload["id"]),
            kind=kind,
            color=color,
            position=position,
            size=size,
            animation=animation,
        )

    def position_at(self, frame: int) -> tuple[float, float]:
        """Return the position of the object for ``frame``."""

        if self.animation is None:
            return self.position
        return self.animation.position_at(frame)

    def render(self, target: "Frame", frame_index: int) -> None:
        """Draw the object on ``target``."""

        if self.kind == "rectangle":
            self._render_rectangle(target, frame_index)
        elif self.kind == "circle":
            self._render_circle(target, frame_index)
        else:  # pragma: no cover - defensive
            supported = ", ".join(SUPPORTED_OBJECT_TYPES)
            raise SceneError(
                f"Unsupported object type: {self.kind!r}. Supported types are: {supported}"
            )

    def _render_rectangle(self, target: "Frame", frame_index: int) -> None:
        position = self.position_at(frame_index)
        width, height = self.size
        left = int(round(position[0]))
        top = int(round(position[1]))
        right = left + int(round(width))
        bottom = top + int(round(height))

        for y in range(max(0, top), min(target.height, bottom)):
            row = target.pixels[y]
            for x in range(max(0, left), min(target.width, right)):
                row[x] = self.color

    def _render_circle(self, target: "Frame", frame_index: int) -> None:
        position = self.position_at(frame_index)
        width, height = self.size
        min_diameter = min(width, height)
        if min_diameter <= 0:
            raise SceneError(
                f"Circle '{self.id}' must have a positive diameter (got {width}x{height})"
            )

        radius = max(min_diameter / 2.0, 1.0)
        cx = position[0]
        cy = position[1]
        radius_sq = radius * radius

        min_x = max(0, int(round(cx - radius - 1)))
        max_x = min(target.width - 1, int(round(cx + radius + 1)))
        min_y = max(0, int(round(cy - radius - 1)))
        max_y = min(target.height - 1, int(round(cy + radius + 1)))

        for y in range(min_y, max_y + 1):
            row = target.pixels[y]
            for x in range(min_x, max_x + 1):
                dx = x - cx
                dy = y - cy
                if dx * dx + dy * dy <= radius_sq:
                    row[x] = self.color


@dataclass(slots=True)
class Scene:
    """Representation of a renderable scene."""

    width: int
    height: int
    frame_count: int
    background: Color
    objects: list[SceneObject] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Scene":
        """Create a :class:`Scene` instance from ``payload``."""

        required = {"width", "height", "frames"}
        missing = required - payload.keys()
        if missing:
            joined = ", ".join(sorted(missing))
            raise SceneError(f"Scene is missing required key(s): {joined}")

        width_value = payload["width"]
        try:
            width = int(width_value)
        except (TypeError, ValueError) as exc:
            raise SceneError(
                f"Scene width must be an integer value (got {width_value!r})"
            ) from exc
        if width <= 0:
            raise SceneError(f"Scene width must be greater than zero (got {width})")

        height_value = payload["height"]
        try:
            height = int(height_value)
        except (TypeError, ValueError) as exc:
            raise SceneError(
                f"Scene height must be an integer value (got {height_value!r})"
            ) from exc
        if height <= 0:
            raise SceneError(f"Scene height must be greater than zero (got {height})")

        frames_value = payload["frames"]
        try:
            frame_count = int(frames_value)
        except (TypeError, ValueError) as exc:
            raise SceneError(
                f"Scene frame count must be an integer value (got {frames_value!r})"
            ) from exc
        if frame_count <= 0:
            raise SceneError(
                f"Scene frame count must be greater than zero (got {frame_count})"
            )

        background = parse_color(payload.get("background", "#000000"))

        objects_data = payload.get("objects", [])
        if not isinstance(objects_data, Sequence):
            raise SceneError("Scene objects must be supplied as a sequence")

        objects: list[SceneObject] = []
        for index, obj in enumerate(objects_data):
            if not isinstance(obj, Mapping):
                raise SceneError(f"Scene object at index {index} must be a mapping")
            objects.append(SceneObject.from_dict(dict(obj)))

        return cls(
            width=width,
            height=height,
            frame_count=frame_count,
            background=background,
            objects=objects,
        )


@dataclass(slots=True)
class Frame:
    """A single rendered image frame."""

    index: int
    width: int
    height: int
    pixels: list[list[Color]]

    @classmethod
    def blank(cls, index: int, width: int, height: int, color: Color) -> "Frame":
        """Create a blank frame filled with ``color``."""

        pixels = [[color for _ in range(width)] for _ in range(height)]
        return cls(index=index, width=width, height=height, pixels=pixels)

    def _has_alpha(self) -> bool:
        return any(len(pixel) == 4 for row in self.pixels for pixel in row)

    def to_bytes(self, *, mode: str = "RGB") -> bytes:
        """Return the frame encoded as ``mode`` bytes."""

        if mode not in {"RGB", "RGBA"}:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported image mode: {mode}")

        include_alpha = mode == "RGBA"
        raw = bytearray()
        for row in self.pixels:
            for pixel in row:
                r, g, b = pixel[:3]
                raw.extend((r, g, b))
                if include_alpha:
                    alpha = pixel[3] if len(pixel) == 4 else 255
                    raw.append(alpha)
        return bytes(raw)

    def save_ppm(self, destination: Path) -> None:
        """Write the frame to ``destination`` in the plain PPM format."""

        with destination.open("w", encoding="ascii") as stream:
            stream.write(f"P3\n{self.width} {self.height}\n255\n")
            for row in self.pixels:
                values = " ".join("{} {} {}".format(*pixel[:3]) for pixel in row)
                stream.write(values + "\n")

    def to_image(self, *, mode: str | None = None) -> PILImage.Image:
        """Return the frame as a Pillow :class:`~PIL.Image.Image` instance."""

        pillow = _require_pillow()
        has_alpha = self._has_alpha()
        resolved_mode = mode or ("RGBA" if has_alpha else "RGB")
        if resolved_mode not in {"RGB", "RGBA"}:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported image mode: {resolved_mode}")

        data = self.to_bytes(mode=resolved_mode)
        image: PILImage.Image = pillow.frombytes(
            resolved_mode, (self.width, self.height), data
        )
        return image

    def save_png(
        self, destination: Path, *, mode: str | None = None, **options: Any
    ) -> None:
        """Write the frame to ``destination`` as a PNG file."""

        image = self.to_image(mode=mode)
        image.save(destination, format="PNG", **options)


class Renderer:
    """Render engine responsible for producing image frames."""

    def __init__(self, scene: Scene):
        self.scene = scene

    def render(self) -> Iterator[Frame]:
        """Yield each rendered frame in the scene lazily."""

        for index in range(self.scene.frame_count):
            frame = Frame.blank(
                index, self.scene.width, self.scene.height, self.scene.background
            )
            for obj in self.scene.objects:
                obj.render(frame, index)
            yield frame


@dataclass(slots=True)
class AnimationWriter:
    """Utility for encoding a sequence of :class:`Frame` objects."""

    frames: Sequence[Frame]
    fps: int = 24

    def _ensure_frames(self) -> list[Frame]:
        if not self.frames:
            raise ValueError("Cannot encode an empty frame sequence")
        if self.fps <= 0:
            raise ValueError("Frames per second must be greater than zero")
        return list(self.frames)

    def write_gif(
        self,
        destination: Path,
        *,
        loop: int = 0,
        optimize: bool = True,
        duration_ms: int | None = None,
    ) -> None:
        """Write the frames to ``destination`` as an animated GIF."""

        frames = self._ensure_frames()
        images = [frame.to_image(mode="RGBA") for frame in frames]
        first = images[0]
        rest = images[1:]
        duration = (
            duration_ms
            if duration_ms is not None
            else max(int(round(1000 / self.fps)), 1)
        )
        first.save(
            destination,
            format="GIF",
            save_all=True,
            append_images=rest,
            duration=duration,
            loop=loop,
            disposal=2,
            optimize=optimize,
        )

    def write_mp4(
        self,
        destination: Path,
        *,
        codec: str = "libx264",
        bitrate: str | None = None,
        pixelformat: str = "yuv420p",
    ) -> None:
        """Encode the frames into an MP4 container using :mod:`imageio`."""

        module = _require_imageio()
        kwargs: dict[str, Any] = {
            "fps": self.fps,
            "codec": codec,
            "pixelformat": pixelformat,
        }
        if bitrate is not None:
            kwargs["bitrate"] = bitrate

        frames = self._ensure_frames()
        numpy = _require_numpy()
        with module.get_writer(
            destination, format="ffmpeg", mode="I", **kwargs
        ) as stream:
            for frame in frames:
                image = frame.to_image(mode="RGB")
                stream.append_data(numpy.asarray(image))

    def write(self, destination: Path) -> None:
        """Auto-detect the output format based on ``destination``'s suffix."""

        suffix = destination.suffix.lower()
        if suffix == ".gif":
            self.write_gif(destination)
        elif suffix in {".mp4", ".m4v"}:
            self.write_mp4(destination)
        else:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported animation format for '{destination}'")


def parse_color(value: object) -> Color:
    """Parse ``value`` into an RGB(A) tuple with components in the 0-255 range."""

    def _validate_components(components: Sequence[int]) -> None:
        for component in components:
            if not 0 <= component <= 255:
                raise SceneError(
                    f"Colour component {component} is outside the expected 0-255 range"
                )

    if isinstance(value, str):
        text = value.lstrip("#")
        if len(text) in {3, 4}:
            text = "".join(ch * 2 for ch in text)
        if len(text) not in {6, 8}:
            raise SceneError(f"Could not parse colour value: {value!r}")
        try:
            r = int(text[0:2], 16)
            g = int(text[2:4], 16)
            b = int(text[4:6], 16)
            if len(text) == 8:
                a = int(text[6:8], 16)
                components = (r, g, b, a)
                _validate_components(components)
                return components
        except ValueError as exc:  # pragma: no cover - defensive
            raise SceneError(f"Could not parse colour value: {value!r}") from exc
        components = (r, g, b)  # type: ignore[assignment]
        _validate_components(components)
        return components

    if isinstance(value, Sequence) and len(value) in {3, 4}:
        try:
            components = tuple(int(component) for component in value)  # type: ignore[assignment]
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise SceneError(f"Could not parse colour value: {value!r}") from exc
        _validate_components(components)
        if len(components) == 4:
            return components
        r, g, b = components
        return r, g, b

    raise SceneError(f"Could not parse colour value: {value!r}")


__all__ = [
    "Animation",
    "AnimationWriter",
    "Frame",
    "Keyframe",
    "Renderer",
    "Scene",
    "SceneError",
    "SceneObject",
    "parse_color",
]
