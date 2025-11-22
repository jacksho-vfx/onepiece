"""Lightweight scene renderer used by the Chopper application."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import itertools
import math
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

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


def _blend_colors(destination: Color, source: Color) -> Color:
    """Return the result of alpha blending ``source`` over ``destination``."""

    src_values: Sequence[int] = source
    dst_values: Sequence[int] = destination

    src_r, src_g, src_b = src_values[:3]
    dst_r, dst_g, dst_b = dst_values[:3]

    src_has_alpha = len(src_values) >= 4
    dst_has_alpha = len(dst_values) >= 4
    include_alpha = src_has_alpha or dst_has_alpha

    src_a = src_values[3] if src_has_alpha else 255
    dst_a = dst_values[3] if dst_has_alpha else 255

    src_alpha = src_a / 255.0
    dst_alpha = dst_a / 255.0

    out_alpha = src_alpha + dst_alpha * (1.0 - src_alpha)
    if out_alpha == 0:
        return (0, 0, 0, 0) if include_alpha else (0, 0, 0)

    out_r = int(
        round((src_r * src_alpha + dst_r * dst_alpha * (1.0 - src_alpha)) / out_alpha)
    )
    out_g = int(
        round((src_g * src_alpha + dst_g * dst_alpha * (1.0 - src_alpha)) / out_alpha)
    )
    out_b = int(
        round((src_b * src_alpha + dst_b * dst_alpha * (1.0 - src_alpha)) / out_alpha)
    )
    out_a = int(round(out_alpha * 255.0))

    if include_alpha:
        return (out_r, out_g, out_b, out_a)

    return (out_r, out_g, out_b)


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


EASING_PATTERN = re.compile(
    r"cubic(?:-bezier)?\(([^,]+),([^,]+),([^,]+),([^\)]+)\)", re.IGNORECASE
)


def _validate_easing_identifier(value: object) -> str:
    """Validate and normalise an easing identifier."""

    if not isinstance(value, str):
        raise SceneError("Easing value must be a string identifier")

    text = value.strip().lower()
    if not text:
        raise SceneError("Easing value cannot be empty")

    if text in {"linear", "ease-in", "ease-out", "ease-in-out"}:
        return text

    match = EASING_PATTERN.fullmatch(text)
    if match:
        try:
            x1, y1, x2, y2 = (float(part) for part in match.groups())
        except ValueError as exc:  # pragma: no cover - defensive
            raise SceneError(f"Invalid cubic easing values: {value!r}") from exc

        for component in (x1, y1, x2, y2):
            if not math.isfinite(component):
                raise SceneError("Cubic easing components must be finite numbers")

        return f"cubic({x1},{y1},{x2},{y2})"

    raise SceneError(
        f"Unsupported easing function: {value!r}."
        " Supported values include linear, ease-in, ease-out, ease-in-out,"
        " or cubic(x1,y1,x2,y2)."
    )


def _cubic_bezier(x1: float, y1: float, x2: float, y2: float, t: float) -> float:
    """Evaluate a cubic-bezier curve for progress ``t``."""

    def bezier(a1: float, a2: float, progress: float) -> float:
        inv_t = 1.0 - progress
        return (
            3 * a1 * inv_t * inv_t * progress
            + 3 * a2 * inv_t * progress * progress
            + progress * progress * progress
        )

    # Invert the x curve to find the parametric position for the supplied t
    # then compute the corresponding y value.
    target = t
    lower = 0.0
    upper = 1.0
    for _ in range(12):
        mid = (lower + upper) / 2.0
        estimate = bezier(x1, x2, mid)
        if abs(estimate - target) < 1e-6:
            break
        if estimate < target:
            lower = mid
        else:
            upper = mid
    return bezier(y1, y2, (lower + upper) / 2.0)


def _easing_function(identifier: str | None) -> Callable[[float], float]:
    """Return an easing function for ``identifier``."""

    if identifier is None:
        return lambda t: t

    easing = identifier
    if easing == "linear":
        return lambda t: t
    if easing == "ease-in":
        return lambda t: t * t
    if easing == "ease-out":
        return lambda t: 1 - (1 - t) * (1 - t)
    if easing == "ease-in-out":

        def ease_in_out(t: float) -> float:
            if t < 0.5:
                return 2 * t * t
            return 1 - 2 * (1 - t) * (1 - t)

        return ease_in_out
    if easing.startswith("cubic("):
        x1, y1, x2, y2 = (float(part) for part in easing[6:-1].split(","))
        return lambda t: _cubic_bezier(x1, y1, x2, y2, t)

    # This should not occur because identifiers are validated when parsing.
    return lambda t: t


@dataclass(slots=True)
class Keyframe:
    """Represents a single keyframe in an animation track."""

    frame: int
    x: float
    y: float
    rotation: float
    color: Color | None = None
    easing: str | None = None


@dataclass(slots=True)
class Animation:
    """Simple linear animation track for two-dimensional positions."""

    keyframes: list[Keyframe]
    default_easing: str | None = None

    def transform_at(self, frame: int) -> tuple[float, float, float]:
        """Return the interpolated position and rotation for ``frame``."""

        if not self.keyframes:
            raise SceneError("Animation track defined without any keyframes")

        if frame <= self.keyframes[0].frame:
            start = self.keyframes[0]
            return start.x, start.y, start.rotation

        if frame >= self.keyframes[-1].frame:
            end = self.keyframes[-1]
            return end.x, end.y, end.rotation

        for left, right in pairwise(self.keyframes):
            if left.frame <= frame <= right.frame:
                if right.frame == left.frame:
                    return left.x, left.y, left.rotation
                raw_t = (frame - left.frame) / (right.frame - left.frame)
                easing = _easing_function(left.easing or self.default_easing)
                t = easing(raw_t)
                x = left.x + (right.x - left.x) * t
                y = left.y + (right.y - left.y) * t
                rotation = left.rotation + (right.rotation - left.rotation) * t
                return x, y, rotation

        end = self.keyframes[-1]
        return end.x, end.y, end.rotation

    def position_at(self, frame: int) -> tuple[float, float]:
        """Return the interpolated position for ``frame``."""

        x, y, _ = self.transform_at(frame)
        return x, y

    def rotation_at(self, frame: int) -> float:
        """Return the interpolated rotation for ``frame``."""

        _, _, rotation = self.transform_at(frame)
        return rotation

    def color_at(self, frame: int, *, default_color: Color) -> Color:
        """Return the interpolated color for ``frame``."""

        def _to_rgba(color: Color) -> tuple[int, int, int, int]:
            r, g, b = color[:3]
            a = color[3] if len(color) >= 4 else 255
            return r, g, b, a

        color_keyframes = [
            keyframe for keyframe in self.keyframes if keyframe.color is not None
        ]
        include_alpha = len(default_color) >= 4 or any(
            len(cast(tuple[int, ...], keyframe.color)) >= 4
            for keyframe in color_keyframes
        )

        def _from_rgba(color: tuple[int, int, int, int]) -> Color:
            r, g, b, a = color
            if include_alpha:
                return r, g, b, a
            return r, g, b

        base_color = _to_rgba(default_color)

        if not color_keyframes:
            return _from_rgba(base_color)

        first = color_keyframes[0]
        last = color_keyframes[-1]

        if frame < first.frame:
            return _from_rgba(base_color)

        if frame >= last.frame:
            return _from_rgba(_to_rgba(last.color or base_color))

        for left, right in pairwise(color_keyframes):
            left_color = _to_rgba(left.color or base_color)
            right_color = _to_rgba(right.color or base_color)
            if left.frame == right.frame:
                return _from_rgba(left_color)
            if left.frame <= frame <= right.frame:
                raw_t = (frame - left.frame) / (right.frame - left.frame)
                easing = _easing_function(left.easing or self.default_easing)
                t = easing(raw_t)
                interpolated = tuple(
                    int(round(component_left + (component_right - component_left) * t))
                    for component_left, component_right in zip(left_color, right_color)
                )
                return _from_rgba(cast(tuple[int, int, int, int], interpolated))

        return _from_rgba(_to_rgba(last.color or base_color))


T = TypeVar("T")


def pairwise(values: Iterable[T]) -> Iterator[tuple[T, T]]:
    """Yield the values in ``values`` two at a time."""

    it = iter(values)
    prev = next(it)
    for current in it:
        yield prev, current
        prev = current


SUPPORTED_OBJECT_TYPES: tuple[str, ...] = ("rectangle", "circle", "line", "polygon")


def _parse_rotation_value(value: object, *, default: float = 0.0) -> float:
    """Parse ``value`` into a rotation in radians."""

    if value is None:
        return default

    unit = "degrees"
    magnitude: object = value

    if isinstance(value, Mapping):
        has_degrees = "degrees" in value
        has_radians = "radians" in value
        if has_degrees == has_radians:
            raise SceneError(
                "Rotation mapping must specify exactly one of 'degrees' or 'radians'"
            )
        if has_degrees:
            magnitude = value["degrees"]
        else:
            unit = "radians"
            magnitude = value["radians"]

    try:
        rotation_value = float(cast(float | int | str, magnitude))
    except (TypeError, ValueError) as exc:
        raise SceneError("Rotation must be a numeric value") from exc

    if not math.isfinite(rotation_value):
        raise SceneError("Rotation must be a finite number")

    if unit == "degrees":
        return math.radians(rotation_value)
    return rotation_value


@dataclass(slots=True)
class SceneObject:
    """Renderable object within a scene."""

    id: str
    kind: str
    color: Color
    position: tuple[float, float]
    size: tuple[float, float]
    rotation: float = 0.0
    z_index: int = 0
    points: tuple[tuple[float, float], ...] = ()
    stroke_color: Color | None = None
    stroke_width: float | None = None
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
        try:
            position_x = float(position_data[0])
            position_y = float(position_data[1])
        except (TypeError, ValueError) as exc:
            raise SceneError(
                "Object position must contain numeric x and y values"
            ) from exc

        if not math.isfinite(position_x) or not math.isfinite(position_y):
            raise SceneError("Object position coordinates must be finite numbers")

        position = position_x, position_y

        rotation = _parse_rotation_value(payload.get("rotation"), default=0.0)

        size: tuple[float, float] = (0.0, 0.0)
        size_data = payload.get("size")
        if kind in {"rectangle", "circle"}:
            if size_data is None:
                raise SceneError("Rectangle and circle objects must define a size")
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
        elif size_data is not None:
            if not isinstance(size_data, Sequence) or len(size_data) != 2:
                raise SceneError("Object size must be a length two sequence")
            try:
                size = float(size_data[0]), float(size_data[1])
            except (TypeError, ValueError) as exc:
                raise SceneError(
                    "Object size must contain numeric width and height values"
                ) from exc

        points: tuple[tuple[float, float], ...] = ()
        if kind in {"line", "polygon"}:
            if "points" not in payload:
                raise SceneError(f"{kind.title()} objects must define a set of points")

            points_data = payload["points"]
            if not isinstance(points_data, Sequence):
                raise SceneError("Object points must be supplied as a sequence")

            parsed_points: list[tuple[float, float]] = []
            for index, entry in enumerate(points_data):
                if not isinstance(entry, Sequence) or len(entry) != 2:
                    raise SceneError(
                        f"Object point at index {index} must be a length two sequence"
                    )
                try:
                    x = float(entry[0])
                    y = float(entry[1])
                except (TypeError, ValueError) as exc:
                    raise SceneError(
                        f"Object point at index {index} must contain numeric coordinates"
                    ) from exc
                if not math.isfinite(x) or not math.isfinite(y):
                    raise SceneError(
                        f"Object point at index {index} must be finite numbers"
                    )
                parsed_points.append((x, y))

            if kind == "line" and len(parsed_points) != 2:
                raise SceneError("Line objects must contain exactly 2 point(s)")
            if kind == "polygon" and len(parsed_points) < 3:
                raise SceneError("Polygon objects must contain at least 3 point(s)")
            if len(parsed_points) > 1000:
                raise SceneError(
                    "Object points exceeds maximum supported length (1000)"
                )

            points = tuple(parsed_points)

        stroke_color: Color | None = None
        stroke_width: float | None = None
        stroke_width_raw = payload.get("stroke_width")
        stroke_width_value = cast(float | int | str | None, stroke_width_raw)
        if stroke_width_value is not None:
            try:
                parsed_stroke_width = float(stroke_width_value)
            except (TypeError, ValueError) as exc:
                raise SceneError("Object stroke width must be numeric") from exc
            if not math.isfinite(parsed_stroke_width) or parsed_stroke_width < 0:
                raise SceneError("Object stroke width must be a non-negative number")
            stroke_width = parsed_stroke_width
        elif kind in {"line", "polygon"}:
            stroke_width = 1.0
        if stroke_width is not None and kind == "line" and stroke_width <= 0:
            raise SceneError("Line stroke width must be greater than zero")

        if payload.get("stroke_color") is not None:
            stroke_color = parse_color(payload["stroke_color"])

        z_index_raw = payload.get("z_index", 0)
        if not isinstance(z_index_raw, (int, float)):
            raise SceneError("Object z_index must be an integer")
        z_index_value = float(z_index_raw)
        if not math.isfinite(z_index_value) or not z_index_value.is_integer():
            raise SceneError("Object z_index must be an integer")
        z_index = int(z_index_value)

        default_easing_raw = payload.get("easing")
        default_easing = None
        if default_easing_raw is not None:
            default_easing = _validate_easing_identifier(default_easing_raw)

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

                if not math.isfinite(x) or not math.isfinite(y):
                    raise SceneError(
                        f"Object animation entry at index {index} must have finite coordinate values"
                    )

                rotation_value = _parse_rotation_value(
                    item.get("rotation"), default=rotation
                )

                color_value = None
                if item.get("color") is not None:
                    color_value = parse_color(item["color"])

                easing_raw = item.get("easing")
                easing = None
                if easing_raw is not None:
                    easing = _validate_easing_identifier(easing_raw)

                keyframes.append(
                    Keyframe(
                        frame=frame,
                        x=x,
                        y=y,
                        rotation=rotation_value,
                        color=color_value,
                        easing=easing,
                    )
                )

            if not keyframes:
                raise SceneError(
                    "Object's animation must contain at least one keyframe"
                )

            sorted_keyframes = sorted(keyframes, key=lambda keyframe: keyframe.frame)

            if keyframes != sorted_keyframes:
                raise SceneError(
                    "Object animation keyframes must be ordered by increasing frame"
                )

            for earlier, later in pairwise(sorted_keyframes):
                if later.frame == earlier.frame:
                    raise SceneError(
                        "Object animation keyframes must use unique frame numbers"
                    )

            animation = Animation(
                keyframes=sorted_keyframes, default_easing=default_easing
            )

        return cls(
            id=str(payload["id"]),
            kind=kind,
            color=color,
            position=position,
            size=size,
            rotation=rotation,
            z_index=z_index,
            points=points,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            animation=animation,
        )

    def position_at(self, frame: int) -> tuple[float, float]:
        """Return the position of the object for ``frame``."""

        if self.animation is None:
            return self.position
        return self.animation.position_at(frame)

    def rotation_at(self, frame: int) -> float:
        """Return the rotation of the object (in radians) for ``frame``."""

        if self.animation is None:
            return self.rotation
        return self.animation.rotation_at(frame)

    def color_at(self, frame: int) -> Color:
        """Return the color of the object for ``frame``."""

        if self.animation is None:
            return self.color
        return self.animation.color_at(frame, default_color=self.color)

    def _frame_transform(self, frame: int) -> tuple[tuple[float, float], float]:
        """Return the position and rotation for ``frame``."""

        if self.animation is None:
            return self.position, self.rotation
        x, y, rotation = self.animation.transform_at(frame)
        return (x, y), rotation

    def render(self, target: "Frame", frame_index: int) -> None:
        """Draw the object on ``target``."""

        if self.kind == "rectangle":
            self._render_rectangle(target, frame_index)
        elif self.kind == "circle":
            self._render_circle(target, frame_index)
        elif self.kind == "line":
            self._render_line(target, frame_index)
        elif self.kind == "polygon":
            self._render_polygon(target, frame_index)
        else:  # pragma: no cover - defensive
            supported = ", ".join(SUPPORTED_OBJECT_TYPES)
            raise SceneError(
                f"Unsupported object type: {self.kind!r}. Supported types are: {supported}"
            )

    def _render_rectangle(self, target: "Frame", frame_index: int) -> None:
        origin, rotation = self._frame_transform(frame_index)
        width, height = self.size
        corners = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
        points = self._rotate_and_translate_points(corners, origin, rotation)

        self._fill_polygon(target, points, self.color_at(frame_index))

        _, stroke_width = self._stroke_details(frame_index)
        if stroke_width > 0:
            for index, start in enumerate(points):
                end = points[(index + 1) % len(points)]
                self._draw_line(target, start, end, frame_index)

    def _render_circle(self, target: "Frame", frame_index: int) -> None:
        position = self.position_at(frame_index)
        color = self.color_at(frame_index)
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
                    target._blend_into(row, x, color)

        stroke_color, stroke_width = self._stroke_details(frame_index)
        if stroke_width > 0:
            segments = max(12, int(math.ceil(radius * 6)))
            points = [
                (
                    cx + radius * math.cos((2 * math.pi * index) / segments),
                    cy + radius * math.sin((2 * math.pi * index) / segments),
                )
                for index in range(segments)
            ]

            for index, start in enumerate(points):
                end = points[(index + 1) % len(points)]
                self._draw_line(
                    target, start, end, frame_index, stroke_color=stroke_color
                )

    def _stroke_details(self, frame_index: int) -> tuple[Color, int]:
        stroke_color = self.stroke_color or self.color_at(frame_index)
        stroke_width_value = 1.0 if self.stroke_width is None else self.stroke_width
        stroke_width = max(0, int(round(stroke_width_value)))
        return stroke_color, stroke_width

    def _rotate_and_translate_points(
        self,
        points: Sequence[tuple[float, float]],
        origin: tuple[float, float],
        rotation: float,
    ) -> list[tuple[float, float]]:
        origin_x, origin_y = origin
        if rotation == 0:
            return [(x + origin_x, y + origin_y) for x, y in points]

        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        rotated = []
        for x, y in points:
            rx = x * cos_r - y * sin_r
            ry = x * sin_r + y * cos_r
            rotated.append((rx + origin_x, ry + origin_y))
        return rotated

    def _transformed_points(self, frame_index: int) -> list[tuple[float, float]]:
        origin, rotation = self._frame_transform(frame_index)
        return self._rotate_and_translate_points(self.points, origin, rotation)

    def _draw_point(
        self, target: "Frame", x: float, y: float, stroke_width: int, color: Color
    ) -> None:
        half = max(0.0, (stroke_width - 1) / 2)
        min_x = max(0, int(math.floor(x - half)))
        max_x = min(target.width - 1, int(math.ceil(x + half)))
        min_y = max(0, int(math.floor(y - half)))
        max_y = min(target.height - 1, int(math.ceil(y + half)))

        for yy in range(min_y, max_y + 1):
            row = target.pixels[yy]
            for xx in range(min_x, max_x + 1):
                target._blend_into(row, xx, color)

    def _draw_line(
        self,
        target: "Frame",
        start: tuple[float, float],
        end: tuple[float, float],
        frame_index: int,
        *,
        stroke_color: Color | None = None,
    ) -> None:
        stroke_color_value, stroke_width = self._stroke_details(frame_index)
        resolved_stroke_color = stroke_color or stroke_color_value
        if stroke_width <= 0:
            return
        x0, y0 = start
        x1, y1 = end

        dx = x1 - x0
        dy = y1 - y0
        steps = max(int(round(max(abs(dx), abs(dy)))), 1)

        for step in range(steps + 1):
            t = step / steps
            x = x0 + dx * t
            y = y0 + dy * t
            self._draw_point(target, x, y, stroke_width, resolved_stroke_color)

    def _render_line(self, target: "Frame", frame_index: int) -> None:
        points = self._transformed_points(frame_index)
        self._draw_line(target, points[0], points[1], frame_index)

    def _render_polygon(self, target: "Frame", frame_index: int) -> None:
        points = self._transformed_points(frame_index)
        if len(points) < 3:
            raise SceneError("Polygon must contain at least three points")

        self._fill_polygon(target, points, self.color_at(frame_index))

        stroke_color, stroke_width = self._stroke_details(frame_index)
        if stroke_width > 0:
            for i, start in enumerate(points):
                end = points[(i + 1) % len(points)]
                self._draw_line(
                    target, start, end, frame_index, stroke_color=stroke_color
                )

    def _fill_polygon(
        self, target: "Frame", points: Sequence[tuple[float, float]], color: Color
    ) -> None:
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        min_x = max(0, int(math.floor(min(xs))))
        max_x = min(target.width - 1, int(math.ceil(max(xs))))
        min_y = max(0, int(math.floor(min(ys))))
        max_y = min(target.height - 1, int(math.ceil(max(ys))))

        # Fill polygon using an even-odd rule scanline approach.
        for y in range(min_y, max_y + 1):
            row = target.pixels[y]
            intersections: list[float] = []
            for i, (x1, y1) in enumerate(points):
                x2, y2 = points[(i + 1) % len(points)]
                if y1 == y2:
                    continue
                if (y1 <= y < y2) or (y2 <= y < y1):
                    x_int = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
                    intersections.append(x_int)

            intersections.sort()
            for index in range(0, len(intersections), 2):
                if index + 1 >= len(intersections):
                    break
                left = intersections[index]
                right = intersections[index + 1]
                start_x = int(math.ceil(left))
                end_x = int(math.floor(right))
                for x in range(max(min_x, start_x), min(max_x, end_x) + 1):
                    target._blend_into(row, x, color)


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

        if not isinstance(payload, Mapping):
            raise SceneError("Scene description must be a mapping")

        payload = dict(payload)

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
        seen_ids: set[str] = set()
        for index, obj in enumerate(objects_data):
            if not isinstance(obj, Mapping):
                raise SceneError(f"Scene object at index {index} must be a mapping")
            scene_object = SceneObject.from_dict(dict(obj))
            if scene_object.id in seen_ids:
                raise SceneError(
                    f"Scene object ids must be unique (duplicate id {scene_object.id!r})"
                )
            seen_ids.add(scene_object.id)
            objects.append(scene_object)

        objects.sort(key=lambda obj: obj.z_index)

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
    has_alpha: bool | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.has_alpha is None:
            self.has_alpha = any(
                len(pixel) >= 4 for row in self.pixels for pixel in row
            )

    def _update_alpha_flag(self, pixel: Color) -> None:
        if self.has_alpha is not True and len(pixel) >= 4:
            self.has_alpha = True

    def _blend_into(self, row: list[Color], x: int, color: Color) -> None:
        blended = _blend_colors(row[x], color)
        row[x] = blended
        self._update_alpha_flag(blended)

    @classmethod
    def blank(cls, index: int, width: int, height: int, color: Color) -> "Frame":
        """Create a blank frame filled with ``color``."""

        pixels = [[color for _ in range(width)] for _ in range(height)]
        return cls(
            index=index,
            width=width,
            height=height,
            pixels=pixels,
            has_alpha=len(color) >= 4,
        )

    def _has_alpha(self) -> bool:
        if self.has_alpha is None:
            self.has_alpha = any(
                len(pixel) >= 4 for row in self.pixels for pixel in row
            )
        return self.has_alpha

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

    def render(self, frames: Iterable[int] | None = None) -> Iterator[Frame]:
        """Yield selected rendered frames lazily.

        Parameters
        ----------
        frames:
            Optional iterable of frame indices to render. If omitted, all frames in the
            scene will be produced.
        """

        if frames is None:
            frame_indices = list(range(self.scene.frame_count))
        else:
            frame_indices = list(frames)
            if not frame_indices:
                raise SceneError("No frame indices were supplied for rendering")
            for index in frame_indices:
                if index < 0 or index >= self.scene.frame_count:
                    raise SceneError(
                        f"Frame index {index} is outside the 0-{self.scene.frame_count - 1} range"
                    )

        for index in frame_indices:
            frame = Frame.blank(
                index, self.scene.width, self.scene.height, self.scene.background
            )
            for obj in self.scene.objects:
                obj.render(frame, index)
            yield frame


@dataclass(slots=True)
class AnimationWriter:
    """Utility for encoding a sequence of :class:`Frame` objects."""

    frames: Iterable[Frame]
    fps: int = 24

    def _validate_and_split_frames(self) -> tuple[Frame, Iterator[Frame]]:
        if self.fps <= 0:
            raise ValueError("Frames per second must be greater than zero")

        iterator = iter(self.frames)
        try:
            first = next(iterator)
        except StopIteration:
            raise ValueError("Cannot encode an empty frame sequence") from None

        return first, iterator

    def write_gif(
        self,
        destination: Path,
        *,
        loop: int = 0,
        optimize: bool = True,
        duration_ms: int | None = None,
    ) -> int:
        """Write the frames to ``destination`` as an animated GIF."""

        first, rest = self._validate_and_split_frames()
        images = [first.to_image(mode="RGBA")]
        images.extend(frame.to_image(mode="RGBA") for frame in rest)
        duration = (
            duration_ms
            if duration_ms is not None
            else max(int(round(1000 / self.fps)), 1)
        )
        first_image, *remaining = images
        first_image.save(
            destination,
            format="GIF",
            save_all=True,
            append_images=remaining,
            duration=duration,
            loop=loop,
            disposal=2,
            optimize=optimize,
        )

        return len(images)

    def write_mp4(
        self,
        destination: Path,
        *,
        codec: str = "libx264",
        bitrate: str | None = None,
        pixelformat: str = "yuv420p",
    ) -> int:
        """Encode the frames into an MP4 container using :mod:`imageio`."""

        module = _require_imageio()
        kwargs: dict[str, Any] = {
            "fps": self.fps,
            "codec": codec,
            "pixelformat": pixelformat,
        }
        if bitrate is not None:
            kwargs["bitrate"] = bitrate

        first, rest = self._validate_and_split_frames()
        numpy = _require_numpy()
        frame_count = 0
        with module.get_writer(
            destination, format="ffmpeg", mode="I", **kwargs
        ) as stream:
            for frame in itertools.chain((first,), rest):
                image = frame.to_image(mode="RGB")
                stream.append_data(numpy.asarray(image))

                frame_count += 1

        return frame_count

    def write(self, destination: Path) -> int:
        """Auto-detect the output format based on ``destination``'s suffix."""

        suffix = destination.suffix.lower()
        if suffix == ".gif":
            return self.write_gif(destination)
        elif suffix in {".mp4", ".m4v"}:
            return self.write_mp4(destination)
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
