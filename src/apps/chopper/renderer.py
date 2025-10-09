"""Lightweight scene renderer used by the Chopper application."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence, Any

Color = tuple[int, int, int]


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

        color = parse_color(payload["color"])

        position_data = payload["position"]
        if not isinstance(position_data, Sequence) or len(position_data) != 2:
            raise SceneError("Object position must be a length two sequence")
        position = float(position_data[0]), float(position_data[1])

        size_data = payload.get("size", (0, 0))
        if not isinstance(size_data, Sequence) or len(size_data) != 2:
            raise SceneError("Object size must be a length two sequence")
        size = float(size_data[0]), float(size_data[1])

        animation_data: list[dict[str, Any]] = payload.get("animation")  # type: ignore[assignment]
        animation = None
        if animation_data is not None:
            animation = Animation(
                keyframes=[
                    Keyframe(
                        frame=int(item["frame"]),
                        x=float(item.get("x", position[0])),
                        y=float(item.get("y", position[1])),
                    )
                    for item in sorted(animation_data, key=lambda it: int(it["frame"]))
                ]
            )

        return cls(
            id=str(payload["id"]),
            kind=str(payload["type"]),
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
            raise SceneError(f"Unsupported object type: {self.kind}")

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
        radius = self.size[0] / 2 if self.size[0] else self.size[1] / 2
        radius = max(radius, 1.0)
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

        width = int(payload["width"])
        height = int(payload["height"])
        frame_count = int(payload["frames"])

        background = parse_color(payload.get("background", "#000000"))

        objects_data = payload.get("objects", [])
        if not isinstance(objects_data, Sequence):
            raise SceneError("Scene objects must be supplied as a sequence")

        objects = [SceneObject.from_dict(obj) for obj in objects_data]

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

    def to_bytes(self) -> bytes:
        """Return the frame encoded as 24-bit RGB bytes."""

        raw = bytearray()
        for row in self.pixels:
            for r, g, b in row:
                raw.extend((r, g, b))
        return bytes(raw)

    def save_ppm(self, destination: Path) -> None:
        """Write the frame to ``destination`` in the plain PPM format."""

        with destination.open("w", encoding="ascii") as stream:
            stream.write(f"P3\n{self.width} {self.height}\n255\n")
            for row in self.pixels:
                values = " ".join("{} {} {}".format(*pixel) for pixel in row)
                stream.write(values + "\n")


class Renderer:
    """Render engine responsible for producing image frames."""

    def __init__(self, scene: Scene):
        self.scene = scene

    def render(self) -> list[Frame]:
        """Render every frame in the scene."""

        frames: list[Frame] = []
        for index in range(self.scene.frame_count):
            frame = Frame.blank(
                index, self.scene.width, self.scene.height, self.scene.background
            )
            for obj in self.scene.objects:
                obj.render(frame, index)
            frames.append(frame)
        return frames


def parse_color(value: object) -> Color:
    """Parse ``value`` into an RGB tuple."""

    if isinstance(value, str):
        text = value.lstrip("#")
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        if len(text) != 6:
            raise SceneError(f"Could not parse colour value: {value!r}")
        try:
            r = int(text[0:2], 16)
            g = int(text[2:4], 16)
            b = int(text[4:6], 16)
        except ValueError as exc:  # pragma: no cover - defensive
            raise SceneError(f"Could not parse colour value: {value!r}") from exc
        return r, g, b

    if isinstance(value, Sequence) and len(value) == 3:
        try:
            r, g, b = (int(component) for component in value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise SceneError(f"Could not parse colour value: {value!r}") from exc
        return r, g, b

    raise SceneError(f"Could not parse colour value: {value!r}")


__all__ = [
    "Animation",
    "Frame",
    "Keyframe",
    "Renderer",
    "Scene",
    "SceneError",
    "SceneObject",
    "parse_color",
]
