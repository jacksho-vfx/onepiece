"""Lightweight scene renderer used by the Chopper application."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
import enum
import itertools
import math
import json
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
    import OpenEXR as _OpenEXR
    import Imath as _Imath
else:
    try:
        import imageio.v3 as iio
    except ImportError:
        iio = None  # type: ignore[assignment]

    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore[assignment]

    try:
        import OpenEXR as _OpenEXR
        import Imath as _Imath
    except ImportError:  # pragma: no cover - handled lazily when export attempted
        _OpenEXR = None  # type: ignore[assignment]
        _Imath = None  # type: ignore[assignment]

OpenEXR = cast("Any", _OpenEXR)
Imath = cast("Any", _Imath)

Color = tuple[int, int, int] | tuple[int, int, int, int] | tuple[int, ...]
BackplatePath = str | Path


class ColorSpace(enum.Enum):
    SRGB = "srgb"
    LINEAR = "linear"

    @classmethod
    def from_value(cls, value: object) -> "ColorSpace":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            normalised = value.strip().lower()
            try:
                return cls(normalised)
            except ValueError as exc:
                options = ", ".join(sorted(member.value for member in cls))
                raise SceneError(f"Colour space must be one of: {options}") from exc
        raise SceneError("Colour space must be provided as a string identifier")


class _OcioMatrixTransform:
    """Simple 3x3 matrix transform used for OCIO-style conversions."""

    def __init__(self, matrix: Sequence[Sequence[float]]):
        numpy = _require_numpy()
        array = numpy.asarray(matrix, dtype=float)
        if array.shape != (3, 3):
            raise SceneError("OCIO matrix transforms must be 3x3 arrays")
        self._matrix = array

    def apply_rgb(self, rgb: Any) -> Any:
        numpy = _require_numpy()
        vector = numpy.asarray(rgb, dtype=float)
        return vector @ self._matrix.T


class _OcioColorSpace:
    """Container for OCIO colour space transforms."""

    def __init__(
        self,
        *,
        name: str,
        to_working: Sequence[Sequence[float]],
        from_working: Sequence[Sequence[float]],
    ) -> None:
        self.name = name
        self.to_working = _OcioMatrixTransform(to_working)
        self.from_working = _OcioMatrixTransform(from_working)


class OcioConfig:
    """Lightweight OCIO-inspired config supporting matrix-based transforms."""

    def __init__(
        self,
        *,
        path: Path,
        display: str | None = None,
        view: str | None = None,
    ) -> None:
        try:
            contents = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise SceneError(f"OCIO config '{path}' was not found") from exc
        except PermissionError as exc:
            raise SceneError(f"OCIO config '{path}' could not be read: {exc}") from exc
        except OSError as exc:  # pragma: no cover - defensive
            raise SceneError(f"OCIO config '{path}' could not be read: {exc}") from exc

        try:
            payload = json.loads(contents)
        except json.JSONDecodeError as exc:
            raise SceneError(f"OCIO config '{path}' is not valid JSON") from exc

        working_space_value = payload.get("working_space")
        if not isinstance(working_space_value, str) or not working_space_value.strip():
            raise SceneError("OCIO config must define a non-empty 'working_space'")
        self.working_space = working_space_value.strip().lower()

        color_spaces_payload = payload.get("color_spaces")
        if not isinstance(color_spaces_payload, Mapping):
            raise SceneError("OCIO config must include a 'color_spaces' mapping")

        self.color_spaces: dict[str, _OcioColorSpace] = {}
        for name, details in color_spaces_payload.items():
            if not isinstance(name, str):
                raise SceneError("OCIO color space names must be strings")
            if not isinstance(details, Mapping):
                raise SceneError("OCIO color space entries must be mappings")
            to_working = details.get("to_working")
            from_working = details.get("from_working")
            if to_working is None or from_working is None:
                raise SceneError(
                    f"OCIO color space '{name}' must define to_working and from_working"
                )
            self.color_spaces[name.lower()] = _OcioColorSpace(
                name=name,
                to_working=cast(Sequence[Sequence[float]], to_working),
                from_working=cast(Sequence[Sequence[float]], from_working),
            )

        if self.working_space not in self.color_spaces:
            raise SceneError(
                f"OCIO working_space '{self.working_space}' is not defined in color_spaces"
            )

        displays_payload = payload.get("displays")
        if not isinstance(displays_payload, Mapping):
            raise SceneError("OCIO config must include a 'displays' mapping")
        self.displays: dict[str, dict[str, str]] = {}
        for display_name, views in displays_payload.items():
            if not isinstance(display_name, str):
                raise SceneError("OCIO display names must be strings")
            if not isinstance(views, Mapping):
                raise SceneError(
                    "OCIO display entries must map view names to color spaces"
                )
            normalized_views: dict[str, str] = {}
            for view_name, colorspace_name in views.items():
                if not isinstance(view_name, str) or not isinstance(
                    colorspace_name, str
                ):
                    raise SceneError("OCIO display views must be string mappings")
                normalized_views[view_name.strip().lower()] = (
                    colorspace_name.strip().lower()
                )
            self.displays[display_name.strip().lower()] = normalized_views

        if not self.displays:
            raise SceneError("OCIO config must define at least one display")

        self.display = self._resolve_display(display)
        self.view = self._resolve_view(view)
        self.output_color_space = self._resolve_output_space()

    def _resolve_display(self, display: str | None) -> str:
        if display is None:
            return next(iter(self.displays))
        normalized = display.strip().lower()
        if normalized not in self.displays:
            available = ", ".join(sorted(self.displays))
            raise SceneError(
                f"OCIO display '{display}' was not found in config (available: {available})"
            )
        return normalized

    def _resolve_view(self, view: str | None) -> str:
        display_views = self.displays[self.display]
        if view is None:
            return next(iter(display_views))
        normalized = view.strip().lower()
        if normalized not in display_views:
            raise SceneError(
                f"OCIO view '{view}' was not found for display '{self.display}'"
            )
        return normalized

    def _resolve_output_space(self) -> str:
        output_space = self.displays[self.display].get(self.view)
        if output_space is None:
            raise SceneError(
                f"OCIO display '{self.display}' view '{self.view}' has no target color space"
            )
        if output_space not in self.color_spaces:
            available = ", ".join(sorted(self.color_spaces))
            raise SceneError(
                f"OCIO view '{self.view}' on display '{self.display}' references unknown "
                f"color space '{output_space}'. Available spaces: {available}"
            )
        return output_space

    def _clamp_array(self, values: Any) -> Any:
        numpy = _require_numpy()
        return numpy.clip(values, 0.0, 1.0)

    def _space_for_color(self, color_space: ColorSpace) -> str:
        if color_space is ColorSpace.SRGB:
            space = "srgb"
        else:
            space = self.working_space
        if space not in self.color_spaces:
            available = ", ".join(sorted(self.color_spaces))
            raise SceneError(
                f"OCIO config does not define a color space for '{color_space.value}'. "
                f"Available: {available}"
            )
        return space

    def to_working(self, color: Color, *, source_space: ColorSpace) -> Color:
        numpy = _require_numpy()
        space_name = self._space_for_color(source_space)
        transform = self.color_spaces[space_name].to_working
        rgb = numpy.asarray(color[:3], dtype=float) / 255.0
        transformed = transform.apply_rgb(rgb)
        clamped = self._clamp_array(transformed)
        alpha = color[3] if len(color) >= 4 else 255
        r, g, b = (int(round(component * 255.0)) for component in clamped)
        if len(color) >= 4:
            return r, g, b, alpha
        return r, g, b

    def apply_output_transform(self, buffer: Any) -> Any:
        if self.output_color_space == self.working_space:
            return self._clamp_array(buffer)
        transform = self.color_spaces[self.output_color_space].from_working
        rgb = buffer[:, :, :3]
        transformed = transform.apply_rgb(rgb)
        buffer[:, :, :3] = self._clamp_array(transformed)
        return buffer


def _srgb_to_linear_component(component: int) -> float:
    channel = max(0.0, min(255.0, float(component))) / 255.0
    if channel <= 0.04045:
        return channel / 12.92
    return float(((channel + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb_component(component: float) -> int:
    channel = _clamp(component)
    if channel <= 0.0031308:
        encoded = channel * 12.92
    else:
        encoded = 1.055 * (channel ** (1 / 2.4)) - 0.055
    return int(round(encoded * 255.0))


def _decode_component(component: int, color_space: ColorSpace) -> float:
    if color_space is ColorSpace.SRGB:
        return _srgb_to_linear_component(component)
    return max(0.0, min(255.0, float(component))) / 255.0


def _encode_component(component: float, color_space: ColorSpace) -> int:
    if color_space is ColorSpace.SRGB:
        return _linear_to_srgb_component(component)
    return int(round(_clamp(component) * 255.0))


def _draw_stroke_point(
    target: "Frame", x: float, y: float, stroke_width: int, color: Color
) -> None:
    """Draw a stroked point centred on ``(x, y)``."""

    half = max(0.0, (stroke_width - 1) / 2)
    min_x = max(0, int(math.floor(x - half)))
    max_x = min(target.width - 1, int(math.ceil(x + half)))
    min_y = max(0, int(math.floor(y - half)))
    max_y = min(target.height - 1, int(math.ceil(y + half)))

    for yy in range(min_y, max_y + 1):
        row = target.pixels[yy]
        for xx in range(min_x, max_x + 1):
            target._blend_into(row, xx, color)


def _draw_stroke_line(
    target: "Frame",
    start: tuple[float, float],
    end: tuple[float, float],
    stroke_width: int,
    color: Color,
) -> None:
    """Draw a stroked line segment between ``start`` and ``end``."""

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
        _draw_stroke_point(target, x, y, stroke_width, color)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    """Clamp ``value`` to the inclusive ``lower``/``upper`` range."""

    return max(lower, min(upper, value))


def _parse_point(value: object, *, label: str) -> tuple[float, float]:
    """Parse a 2D coordinate from ``value`` or raise :class:`SceneError`."""

    if not isinstance(value, Sequence) or len(value) != 2:
        raise SceneError(f"{label} must be a length two sequence")

    try:
        x = float(value[0])
        y = float(value[1])
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise SceneError(f"{label} values must be numeric") from exc

    if not math.isfinite(x) or not math.isfinite(y):
        raise SceneError(f"{label} values must be finite numbers")

    return x, y


def _interpolate_color(
    left: Color, right: Color, t: float, *, color_space: ColorSpace = ColorSpace.SRGB
) -> Color:
    """Linearly interpolate between ``left`` and ``right`` using ``t``."""

    clamped = _clamp(t)
    include_alpha = len(left) >= 4 or len(right) >= 4
    left_r, left_g, left_b = left[:3]
    right_r, right_g, right_b = right[:3]
    left_a = left[3] if len(left) >= 4 else 255
    right_a = right[3] if len(right) >= 4 else 255

    left_r_lin = _decode_component(left_r, color_space)
    left_g_lin = _decode_component(left_g, color_space)
    left_b_lin = _decode_component(left_b, color_space)
    right_r_lin = _decode_component(right_r, color_space)
    right_g_lin = _decode_component(right_g, color_space)
    right_b_lin = _decode_component(right_b, color_space)

    components = (
        _encode_component(
            left_r_lin + (right_r_lin - left_r_lin) * clamped, color_space
        ),
        _encode_component(
            left_g_lin + (right_g_lin - left_g_lin) * clamped, color_space
        ),
        _encode_component(
            left_b_lin + (right_b_lin - left_b_lin) * clamped, color_space
        ),
        int(round(left_a + (right_a - left_a) * clamped)),
    )

    if include_alpha:
        return components

    r, g, b, _ = components
    return r, g, b


def _normalize_pixel(value: object) -> Color:
    """Convert a Pillow pixel value into a :class:`Color` tuple."""

    if isinstance(value, tuple):
        components = tuple(int(component) for component in value)
        if len(components) == 4:
            return cast(Color, components)
        if len(components) == 3:
            r, g, b = components
            return r, g, b, 255

    if isinstance(value, (int, float)):
        component = int(value)
    else:
        component = 0
    return component, component, component, 255


def _apply_opacity(color: Color, opacity: float) -> Color:
    """Return ``color`` with its alpha multiplied by ``opacity``."""

    clamped_opacity = _clamp(opacity)
    r, g, b = color[:3]
    alpha = color[3] if len(color) >= 4 else 255
    adjusted_alpha = int(round(alpha * clamped_opacity))
    return r, g, b, adjusted_alpha


@dataclass(slots=True)
class GuidesOverlay:
    """Optional guide overlays such as safe areas and grids."""

    safe_frame: bool = False
    action_frame: bool = False
    thirds_grid: bool = False
    center_mark: bool = False
    color: Color = (255, 255, 255)
    opacity: float = 0.5
    stroke_width: float = 1.0

    action_ratio: float = 0.9
    safe_ratio: float = 0.8

    def _stroke_settings(self, scale: int) -> tuple[Color, int]:
        stroke_width = max(1, int(round(self.stroke_width * scale)))
        return _apply_opacity(self.color, self.opacity), stroke_width

    def _draw_inset_frame(
        self, frame: "Frame", *, ratio: float, stroke_width: int, color: Color
    ) -> None:
        usable_width = max(frame.width - 1, 0)
        usable_height = max(frame.height - 1, 0)
        inset_x = (1.0 - ratio) * usable_width / 2.0
        inset_y = (1.0 - ratio) * usable_height / 2.0
        if inset_x < 0 or inset_y < 0:
            return

        points = [
            (inset_x, inset_y),
            (usable_width - inset_x, inset_y),
            (usable_width - inset_x, usable_height - inset_y),
            (inset_x, usable_height - inset_y),
        ]

        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            _draw_stroke_line(frame, start, end, stroke_width, color)

    def _draw_thirds(self, frame: "Frame", *, stroke_width: int, color: Color) -> None:
        max_x = frame.width - 1
        max_y = frame.height - 1
        vertical_positions = (frame.width / 3.0, (frame.width * 2.0) / 3.0)
        horizontal_positions = (frame.height / 3.0, (frame.height * 2.0) / 3.0)

        for x in vertical_positions:
            _draw_stroke_line(frame, (x, 0.0), (x, max_y), stroke_width, color)
        for y in horizontal_positions:
            _draw_stroke_line(frame, (0.0, y), (max_x, y), stroke_width, color)

    def _draw_center_mark(
        self, frame: "Frame", *, stroke_width: int, color: Color
    ) -> None:
        max_extent = min(frame.width, frame.height)
        if max_extent <= 0:
            return

        cx = (frame.width - 1) / 2.0
        cy = (frame.height - 1) / 2.0
        half_length = max(max_extent * 0.05, stroke_width)

        _draw_stroke_line(
            frame, (cx - half_length, cy), (cx + half_length, cy), stroke_width, color
        )
        _draw_stroke_line(
            frame, (cx, cy - half_length), (cx, cy + half_length), stroke_width, color
        )

    def draw(self, frame: "Frame", *, scale: int = 1) -> None:
        if not any(
            (self.safe_frame, self.action_frame, self.thirds_grid, self.center_mark)
        ):
            return

        color, stroke_width = self._stroke_settings(scale)

        if self.action_frame:
            self._draw_inset_frame(
                frame, ratio=self.action_ratio, stroke_width=stroke_width, color=color
            )
        if self.safe_frame:
            self._draw_inset_frame(
                frame, ratio=self.safe_ratio, stroke_width=stroke_width, color=color
            )
        if self.thirds_grid:
            self._draw_thirds(frame, stroke_width=stroke_width, color=color)
        if self.center_mark:
            self._draw_center_mark(frame, stroke_width=stroke_width, color=color)


@dataclass(slots=True)
class SolidFill:
    """Uniform fill colour."""

    color: Color

    @property
    def anchor_color(self) -> Color:
        return self.color

    def sample(
        self,
        _: float,
        __: float,
        *,
        texture_cache: "_TextureCache",
        color_space: ColorSpace = ColorSpace.SRGB,
    ) -> Color:
        return self.color


@dataclass(slots=True)
class LinearGradientFill:
    """Linear gradient fill spanning two points in normalised space."""

    start: tuple[float, float]
    end: tuple[float, float]
    start_color: Color
    end_color: Color

    @property
    def anchor_color(self) -> Color:
        return self.start_color

    def sample(
        self,
        u: float,
        v: float,
        *,
        texture_cache: "_TextureCache",
        color_space: ColorSpace = ColorSpace.SRGB,
    ) -> Color:
        delta_x = self.end[0] - self.start[0]
        delta_y = self.end[1] - self.start[1]
        magnitude = delta_x * delta_x + delta_y * delta_y
        if magnitude == 0:
            return self.start_color

        t = ((u - self.start[0]) * delta_x + (v - self.start[1]) * delta_y) / magnitude
        return _interpolate_color(
            self.start_color, self.end_color, t, color_space=color_space
        )


@dataclass(slots=True)
class RadialGradientFill:
    """Radial gradient fill radiating from a normalised centre."""

    center: tuple[float, float]
    radius: float
    inner_color: Color
    outer_color: Color

    @property
    def anchor_color(self) -> Color:
        return self.inner_color

    def sample(
        self,
        u: float,
        v: float,
        *,
        texture_cache: "_TextureCache",
        color_space: ColorSpace = ColorSpace.SRGB,
    ) -> Color:
        dx = u - self.center[0]
        dy = v - self.center[1]
        distance = math.sqrt(dx * dx + dy * dy)
        if self.radius <= 0:
            return self.inner_color
        t = distance / self.radius
        return _interpolate_color(
            self.inner_color, self.outer_color, t, color_space=color_space
        )


@dataclass(slots=True)
class TextureFill:
    """Image texture stretched across the object's bounds."""

    path: Path

    @property
    def anchor_color(self) -> Color:
        image = _TEXTURE_CACHE.get(self.path)
        return _normalize_pixel(image.getpixel((0, 0)))

    def sample(
        self,
        u: float,
        v: float,
        *,
        texture_cache: "_TextureCache",
        color_space: ColorSpace = ColorSpace.SRGB,
    ) -> Color:
        image = texture_cache.get(self.path)
        clamped_u = _clamp(u)
        clamped_v = _clamp(v)
        x = int(round(clamped_u * (image.width - 1)))
        y = int(round(clamped_v * (image.height - 1)))
        return _normalize_pixel(image.getpixel((x, y)))


Fill = SolidFill | LinearGradientFill | RadialGradientFill | TextureFill


@dataclass(slots=True)
class Backplate:
    """Template describing a still image or numbered backplate sequence."""

    path: BackplatePath
    start_index: int = 0
    color_space: ColorSpace = ColorSpace.SRGB

    def path_for_frame(self, index: int) -> Path:
        frame_number = index + self.start_index
        try:
            formatted = str(self.path).format(frame=frame_number, index=frame_number)
        except Exception as exc:  # pragma: no cover - defensive
            raise SceneError(
                f"Backplate path '{self.path}' could not be formatted for frame {index}"
            ) from exc
        return Path(formatted)


class _TextureCache:
    """Cache of decoded Pillow images used as textures."""

    def __init__(self) -> None:
        self._cache: dict[Path, "PILImage.Image"] = {}

    def get(self, path: Path) -> "PILImage.Image":
        image = self._cache.get(path)
        if image is not None:
            return image

        pil_image = cast("Any", _require_pillow())
        resolved = Path(path)
        if not resolved.is_file():
            raise SceneError(f"Texture file does not exist: {resolved}")
        loaded = cast("PILImage.Image", pil_image.open(resolved).convert("RGBA"))
        self._cache[resolved] = loaded
        return loaded


_TEXTURE_CACHE = _TextureCache()


class _BackplateCache:
    """Cache of decoded and colour-managed backplate frames."""

    def __init__(self) -> None:
        self._cache: dict[
            tuple[Path, int, int, ColorSpace, tuple[str, str, str] | None, ColorSpace],
            Frame,
        ] = {}

    def get(
        self,
        backplate: Backplate,
        *,
        frame_index: int,
        target_width: int,
        target_height: int,
        color_space: ColorSpace,
        color_manager: OcioConfig | None,
    ) -> "Frame":
        resolved = backplate.path_for_frame(frame_index).resolve()
        converter_key: tuple[str, str, str] | None = None
        if color_manager is not None:
            converter_key = (
                color_manager.display,
                color_manager.view,
                color_manager.working_space,
            )
        key = (
            resolved,
            target_width,
            target_height,
            color_space,
            converter_key,
            backplate.color_space,
        )

        cached = self._cache.get(key)
        if cached is not None:
            return cached

        pillow = _require_pillow()
        if not resolved.is_file():
            raise SceneError(f"Backplate file does not exist: {resolved}")

        image = cast("PILImage.Image", pillow.open(resolved).convert("RGBA"))
        if image.width != target_width or image.height != target_height:
            resample = getattr(pillow, "Resampling", pillow)
            image = image.resize(
                (target_width, target_height), resample=resample.NEAREST
            )

        data = list(image.getdata())
        iterator = iter(data)
        pixels: list[list[Color]] = []
        for _ in range(target_height):
            row: list[Color] = []
            for _ in range(target_width):
                pixel = _normalize_pixel(next(iterator))
                if color_manager is not None:
                    pixel = color_manager.to_working(
                        pixel, source_space=backplate.color_space
                    )
                row.append(pixel)
            pixels.append(row)

        frame = Frame(
            index=frame_index,
            width=target_width,
            height=target_height,
            pixels=pixels,
            color_space=color_space,
            has_alpha=True,
        )
        self._cache[key] = frame
        return frame


_BACKPLATE_CACHE = _BackplateCache()


def _object_is_visible(obj: object, frame_index: int) -> bool:
    visibility_check = getattr(obj, "is_visible", None)
    if visibility_check is None:
        return True
    return bool(cast(Callable[[int], object], visibility_check)(frame_index))


def _render_frame_static(
    scene: Scene,
    index: int,
    samples: int,
    filter_name: str,
    guides: GuidesOverlay | None,
) -> Frame:
    def _apply_backplate(target: Frame) -> None:
        if scene.backplate is None:
            return
        backplate_frame = _BACKPLATE_CACHE.get(
            scene.backplate,
            frame_index=index,
            target_width=target.width,
            target_height=target.height,
            color_space=scene.color_space,
            color_manager=getattr(scene, "_color_manager", None),
        )
        target.apply_overlay(backplate_frame)

    guides_frame: Frame | None = None
    if samples == 1:
        frame = Frame.blank(
            index,
            scene.width,
            scene.height,
            scene.background,
            color_space=scene.color_space,
        )
        _apply_backplate(frame)
        for obj in scene.objects:
            if _object_is_visible(obj, index):
                obj.render(frame, index)
        if guides:
            guides_frame = Frame.blank(
                index,
                scene.width,
                scene.height,
                (0, 0, 0, 0),
                color_space=scene.color_space,
            )
            guides.draw(guides_frame, scale=1)
            frame.apply_overlay(guides_frame)
            frame.guides = guides_frame.pixels
        return frame

    scaled_width = scene.width * samples
    scaled_height = scene.height * samples
    supersampled_frame = Frame.blank(
        index,
        scaled_width,
        scaled_height,
        scene.background,
        color_space=scene.color_space,
    )
    _apply_backplate(supersampled_frame)
    for obj in scene.objects:
        if _object_is_visible(obj, index):
            obj.render(supersampled_frame, index, scale=samples)

    if guides:
        guides_frame = Frame.blank(
            index,
            scaled_width,
            scaled_height,
            (0, 0, 0, 0),
            color_space=scene.color_space,
        )
        guides.draw(guides_frame, scale=samples)
        supersampled_frame.apply_overlay(guides_frame)
        guides_frame = guides_frame.downsample(samples, filter_name=filter_name)

    downsampled = supersampled_frame.downsample(samples, filter_name=filter_name)
    if guides_frame is not None:
        downsampled.guides = guides_frame.pixels
    return downsampled


def _validate_unit_point(
    point: tuple[float, float], *, label: str
) -> tuple[float, float]:
    x, y = point
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise SceneError(f"{label} must be in the 0-1 range")
    return point


def _parse_fill(value: object, *, object_id: str) -> Fill:
    """Parse a fill description from ``value``."""

    if isinstance(value, Mapping):
        if "type" not in value:
            raise SceneError(
                f"Object '{object_id}' colour mappings must include a 'type' field"
            )

        fill_type = str(value["type"]).strip().lower()
        if fill_type in {"linear", "linear-gradient", "linear_gradient"}:
            start = _validate_unit_point(
                _parse_point(
                    value.get("from", (0.0, 0.0)), label="Linear gradient 'from'"
                ),
                label="Linear gradient 'from'",
            )
            end = _validate_unit_point(
                _parse_point(value.get("to", (1.0, 0.0)), label="Linear gradient 'to'"),
                label="Linear gradient 'to'",
            )
            colors_value = value.get("colors")
            if not isinstance(colors_value, Sequence) or len(colors_value) != 2:
                raise SceneError(
                    "Linear gradients must provide two colours via a 'colors' sequence"
                )
            start_color = parse_color(colors_value[0])
            end_color = parse_color(colors_value[1])
            return LinearGradientFill(
                start=start, end=end, start_color=start_color, end_color=end_color
            )

        if fill_type in {"radial", "radial-gradient", "radial_gradient"}:
            center = _validate_unit_point(
                _parse_point(
                    value.get("center", (0.5, 0.5)), label="Radial gradient 'center'"
                ),
                label="Radial gradient 'center'",
            )
            try:
                radius = float(value.get("radius", 0.5))
            except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                raise SceneError("Radial gradient radius must be numeric") from exc
            if not math.isfinite(radius) or radius <= 0:
                raise SceneError(
                    "Radial gradient radius must be a positive, finite number"
                )

            colors_value = value.get("colors")
            if not isinstance(colors_value, Sequence) or len(colors_value) != 2:
                raise SceneError(
                    "Radial gradients must provide two colours via a 'colors' sequence"
                )
            inner_color = parse_color(colors_value[0])
            outer_color = parse_color(colors_value[1])
            return RadialGradientFill(
                center=center,
                radius=radius,
                inner_color=inner_color,
                outer_color=outer_color,
            )

        if fill_type == "texture":
            raw_path = value.get("path")
            if not isinstance(raw_path, (str, Path)):
                raise SceneError(
                    "Texture fills must provide a string 'path' to an image file"
                )
            return TextureFill(Path(raw_path))

        raise SceneError(
            f"Unsupported fill type {fill_type!r} for object '{object_id}'."
            " Supported types include linear-gradient, radial-gradient, and texture."
        )

    return SolidFill(parse_color(value))


def _parse_backplate(
    value: object | None, *, color_space: ColorSpace
) -> Backplate | None:
    """Parse a backplate description into a :class:`Backplate`."""

    if value is None:
        return None
    if isinstance(value, (str, Path)):
        return Backplate(path=value, color_space=color_space)
    if isinstance(value, Mapping):
        if "path" not in value:
            raise SceneError("Backplates must include a 'path' entry")
        raw_path = value["path"]
        if not isinstance(raw_path, (str, Path)):
            raise SceneError("Backplate 'path' must be a string or Path")
        start_value = value.get("start_index", 0)
        try:
            start_index = int(cast(int | float | str, start_value))
        except (TypeError, ValueError) as exc:
            raise SceneError("Backplate start_index must be an integer") from exc
        plate_space = ColorSpace.from_value(value.get("color_space", color_space))
        return Backplate(
            path=raw_path, start_index=start_index, color_space=plate_space
        )
    raise SceneError("Backplate must be provided as a string path or mapping")


def _blend_colors(
    destination: Color,
    source: Color,
    *,
    color_space: ColorSpace = ColorSpace.SRGB,
) -> Color:
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

    src_r_lin = _decode_component(src_r, color_space)
    src_g_lin = _decode_component(src_g, color_space)
    src_b_lin = _decode_component(src_b, color_space)
    dst_r_lin = _decode_component(dst_r, color_space)
    dst_g_lin = _decode_component(dst_g, color_space)
    dst_b_lin = _decode_component(dst_b, color_space)

    out_r_lin = (
        src_r_lin * src_alpha + dst_r_lin * dst_alpha * (1.0 - src_alpha)
    ) / out_alpha
    out_g_lin = (
        src_g_lin * src_alpha + dst_g_lin * dst_alpha * (1.0 - src_alpha)
    ) / out_alpha
    out_b_lin = (
        src_b_lin * src_alpha + dst_b_lin * dst_alpha * (1.0 - src_alpha)
    ) / out_alpha
    out_a = int(round(out_alpha * 255.0))

    out_r = _encode_component(out_r_lin, color_space)
    out_g = _encode_component(out_g_lin, color_space)
    out_b = _encode_component(out_b_lin, color_space)

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


def _png_color_options(color_space: ColorSpace) -> dict[str, Any]:
    """Return PNG metadata appropriate for the requested ``color_space``."""

    _require_pillow()
    try:  # pragma: no cover - depends on optional Pillow extras
        from PIL import ImageCms
    except ImportError:  # pragma: no cover - exercised in integration tests
        return {}

    options: dict[str, Any] = {}
    profile: Any | None = None

    try:
        if color_space is ColorSpace.SRGB:
            profile = ImageCms.createProfile("sRGB")
        else:
            create_profile = cast(Callable[..., Any], ImageCms.createProfile)
            profile = create_profile("sRGB", is_linear=True)
    except Exception:
        profile = None
        if color_space is ColorSpace.LINEAR:
            options["gamma"] = 1.0

    if profile is not None:
        try:
            cms_profile = ImageCms.ImageCmsProfile(profile)
            options["icc_profile"] = cms_profile.tobytes()
        except (
            Exception
        ):  # pragma: no cover - defensive fallback when profiles unavailable
            pass

    return options


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


def _require_openexr() -> tuple[Any, Any]:
    """Return OpenEXR + Imath modules or raise a helpful error."""

    if (
        OpenEXR is None or Imath is None
    ):  # pragma: no cover - exercised in integration tests
        raise RuntimeError(
            "OpenEXR is required for EXR export. Install the 'onepiece[chopper-exr]' extra."
        )

    return OpenEXR, Imath


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
class RenderTransform:
    """Coordinate transform derived from camera framing."""

    scale_x: float = 1.0
    scale_y: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0

    def apply_point(self, point: tuple[float, float]) -> tuple[float, float]:
        x, y = point
        return (x + self.offset_x) * self.scale_x, (y + self.offset_y) * self.scale_y

    def apply_size(self, size: tuple[float, float]) -> tuple[float, float]:
        width, height = size
        return width * self.scale_x, height * self.scale_y

    @property
    def stroke_scale(self) -> float:
        return max(self.scale_x, self.scale_y)


def _parse_window(value: object, *, label: str) -> tuple[float, float]:
    if not isinstance(value, Sequence) or len(value) != 2:
        raise SceneError(f"Camera {label} must be a length two sequence")
    try:
        width = float(value[0])
        height = float(value[1])
    except (TypeError, ValueError) as exc:
        raise SceneError(f"Camera {label} values must be numeric") from exc
    if not math.isfinite(width) or not math.isfinite(height):
        raise SceneError(f"Camera {label} values must be finite numbers")
    if width <= 0 or height <= 0:
        raise SceneError(f"Camera {label} values must be greater than zero")
    return width, height


@dataclass(slots=True)
class CameraSettings:
    """Camera metadata controlling rasterisation."""

    pixel_aspect_ratio: float = 1.0
    horizontal_aperture: float | None = None
    vertical_aperture: float | None = None
    focal_length: float | None = None
    overscan: float = 0.0
    active_window: tuple[float, float] | None = None
    safe_window: tuple[float, float] | None = None

    @classmethod
    def from_dict(cls, payload: object) -> "CameraSettings":
        if payload is None:
            return cls()
        if not isinstance(payload, Mapping):
            raise SceneError("Camera settings must be provided as a mapping")

        pixel_aspect_raw = payload.get("pixel_aspect_ratio", 1.0)
        try:
            pixel_aspect_ratio = float(pixel_aspect_raw)
        except (TypeError, ValueError) as exc:
            raise SceneError("Camera pixel_aspect_ratio must be numeric") from exc
        if not math.isfinite(pixel_aspect_ratio) or pixel_aspect_ratio <= 0:
            raise SceneError("Camera pixel_aspect_ratio must be greater than zero")

        overscan_raw = payload.get("overscan", 0.0)
        try:
            overscan = float(overscan_raw)
        except (TypeError, ValueError) as exc:
            raise SceneError("Camera overscan must be numeric") from exc
        if not math.isfinite(overscan) or overscan < 0:
            raise SceneError("Camera overscan must be a non-negative number")

        horizontal_aperture = payload.get("horizontal_aperture")
        vertical_aperture = payload.get("vertical_aperture")
        focal_length = payload.get("focal_length")

        aperture_width = None
        aperture_height = None
        if horizontal_aperture is not None:
            try:
                aperture_width = float(horizontal_aperture)
            except (TypeError, ValueError) as exc:
                raise SceneError("Camera horizontal_aperture must be numeric") from exc
            if not math.isfinite(aperture_width) or aperture_width <= 0:
                raise SceneError("Camera horizontal_aperture must be greater than zero")
        if vertical_aperture is not None:
            try:
                aperture_height = float(vertical_aperture)
            except (TypeError, ValueError) as exc:
                raise SceneError("Camera vertical_aperture must be numeric") from exc
            if not math.isfinite(aperture_height) or aperture_height <= 0:
                raise SceneError("Camera vertical_aperture must be greater than zero")
        focal_value: float | None = None
        if focal_length is not None:
            try:
                focal_value = float(focal_length)
            except (TypeError, ValueError) as exc:
                raise SceneError("Camera focal_length must be numeric") from exc
            if not math.isfinite(focal_value) or focal_value <= 0:
                raise SceneError("Camera focal_length must be greater than zero")

        active_window = None
        if payload.get("active_window") is not None:
            active_window = _parse_window(
                payload["active_window"], label="active_window"
            )

        safe_window = None
        if payload.get("safe_window") is not None:
            safe_window = _parse_window(payload["safe_window"], label="safe_window")

        return cls(
            pixel_aspect_ratio=pixel_aspect_ratio,
            horizontal_aperture=aperture_width,
            vertical_aperture=aperture_height,
            focal_length=focal_value,
            overscan=overscan,
            active_window=active_window,
            safe_window=safe_window,
        )

    def active_ratio(self) -> float:
        if self.active_window is None:
            return 1.0
        if self.horizontal_aperture is None or self.vertical_aperture is None:
            return 1.0
        ratio_x = self.active_window[0] / self.horizontal_aperture
        ratio_y = self.active_window[1] / self.vertical_aperture
        return min(ratio_x, ratio_y, 1.0)

    def safe_ratio(self) -> float:
        if self.safe_window is None:
            return 0.8
        base_width, base_height = self.safe_window
        if self.active_window is not None:
            base_width, base_height = self.active_window
        elif (
            self.horizontal_aperture is not None and self.vertical_aperture is not None
        ):
            base_width, base_height = self.horizontal_aperture, self.vertical_aperture
        ratio_x = self.safe_window[0] / base_width
        ratio_y = self.safe_window[1] / base_height
        return min(ratio_x, ratio_y, 1.0)

    def build_transform(
        self, width: int, height: int
    ) -> tuple[RenderTransform, int, int]:
        overscan_x = width * self.overscan
        overscan_y = height * self.overscan
        base_width = width + 2 * overscan_x
        base_height = height + 2 * overscan_y
        transform = RenderTransform(
            scale_x=self.pixel_aspect_ratio,
            scale_y=1.0,
            offset_x=overscan_x,
            offset_y=overscan_y,
        )
        render_width = int(round(base_width * transform.scale_x))
        render_height = int(round(base_height * transform.scale_y))
        return transform, render_width, render_height


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
class VisibilityKeyframe:
    """Represents a visibility change at a given frame."""

    frame: int
    visible: bool


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
    fill: Fill
    position: tuple[float, float]
    size: tuple[float, float]
    rotation: float = 0.0
    z_index: int = 0
    points: tuple[tuple[float, float], ...] = ()
    stroke_color: Color | None = None
    stroke_width: float | None = None
    start_frame: int | None = None
    end_frame: int | None = None
    visibility: tuple[VisibilityKeyframe, ...] = ()
    animation: Animation | None = None

    @classmethod
    def from_dict(
        cls, payload: dict[str, object], *, frame_count: int | None = None
    ) -> "SceneObject":
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

        fill = _parse_fill(payload["color"], object_id=str(payload["id"]))
        color = fill.anchor_color

        if kind == "line" and not isinstance(fill, SolidFill):
            raise SceneError("Line objects must use a solid colour fill")

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

        start_frame_value = payload.get("start_frame")
        start_frame = None
        if start_frame_value is not None:
            try:
                start_frame_parsed = int(cast(int | float | str, start_frame_value))
            except (TypeError, ValueError) as exc:
                raise SceneError("Object start_frame must be an integer") from exc
            if start_frame_parsed < 0:
                raise SceneError("Object start_frame must be zero or greater")
            start_frame = start_frame_parsed

        end_frame_value = payload.get("end_frame")
        end_frame = None
        if end_frame_value is not None:
            try:
                end_frame_parsed = int(cast(int | float | str, end_frame_value))
            except (TypeError, ValueError) as exc:
                raise SceneError("Object end_frame must be an integer") from exc
            if end_frame_parsed < 0:
                raise SceneError("Object end_frame must be zero or greater")
            end_frame = end_frame_parsed

        if start_frame is not None and end_frame is not None:
            if start_frame > end_frame:
                raise SceneError("Object start_frame cannot be greater than end_frame")

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

        visibility: list[VisibilityKeyframe] = []
        visibility_data = payload.get("visibility")
        if visibility_data is not None:
            if not isinstance(visibility_data, Iterable):
                raise SceneError("Object visibility must be an iterable of mappings")

            for index, entry in enumerate(visibility_data):
                if not isinstance(entry, Mapping):
                    raise SceneError(
                        f"Object visibility entry at index {index} must be a mapping"
                    )
                if "frame" not in entry:
                    raise SceneError(
                        f"Object visibility entry at index {index} is missing a 'frame' value"
                    )
                if "visible" not in entry:
                    raise SceneError(
                        f"Object visibility entry at index {index} is missing a 'visible' value"
                    )

                try:
                    frame_value = int(entry["frame"])
                except (TypeError, ValueError) as exc:
                    raise SceneError(
                        f"Object visibility entry at index {index} has an invalid frame value: {entry['frame']!r}"
                    ) from exc

                if frame_value < 0:
                    raise SceneError(
                        f"Object visibility entry at index {index} must have a non-negative frame number"
                    )

                visible_value = entry["visible"]
                if not isinstance(visible_value, bool):
                    raise SceneError(
                        f"Object visibility entry at index {index} must set 'visible' to a boolean"
                    )

                visibility.append(
                    VisibilityKeyframe(frame=frame_value, visible=visible_value)
                )

            if not visibility:
                raise SceneError("Object visibility must contain at least one entry")

            sorted_visibility = sorted(visibility, key=lambda keyframe: keyframe.frame)

            if visibility != sorted_visibility:
                raise SceneError(
                    "Object visibility keyframes must be ordered by increasing frame"
                )

            for earlier_visibility, later_visibility in pairwise(sorted_visibility):
                if later_visibility.frame == earlier_visibility.frame:
                    raise SceneError(
                        "Object visibility keyframes must use unique frame numbers"
                    )

            visibility = sorted_visibility

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
                    if not isinstance(fill, SolidFill):
                        raise SceneError(
                            "Colour animation is only supported for solid fills"
                        )
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

            for previous_keyframe, next_keyframe in pairwise(sorted_keyframes):
                if next_keyframe.frame == previous_keyframe.frame:
                    raise SceneError(
                        "Object animation keyframes must use unique frame numbers"
                    )

            animation = Animation(
                keyframes=sorted_keyframes, default_easing=default_easing
            )

        if frame_count is not None:
            upper = frame_count - 1
            if start_frame is not None and start_frame > upper:
                raise SceneError(
                    "Object start_frame must be within the scene's frame range"
                )
            if end_frame is not None and end_frame > upper:
                raise SceneError(
                    "Object end_frame must be within the scene's frame range"
                )
            for visibility_keyframe in visibility:
                if visibility_keyframe.frame > upper:
                    raise SceneError(
                        "Object visibility keyframes must be within the scene's frame range"
                    )

        return cls(
            id=str(payload["id"]),
            kind=kind,
            color=color,
            fill=fill,
            position=position,
            size=size,
            rotation=rotation,
            z_index=z_index,
            points=points,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            start_frame=start_frame,
            end_frame=end_frame,
            visibility=tuple(visibility),
            animation=animation,
        )

    def is_visible(self, frame_index: int) -> bool:
        """Return whether the object should be drawn for ``frame_index``."""

        if self.start_frame is not None and frame_index < self.start_frame:
            return False

        if self.end_frame is not None and frame_index > self.end_frame:
            return False

        if not self.visibility:
            return True

        if frame_index < self.visibility[0].frame:
            return False

        for current, next_frame in pairwise(self.visibility):
            if current.frame <= frame_index < next_frame.frame:
                return current.visible

        return self.visibility[-1].visible

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

        if isinstance(self.fill, SolidFill):
            if self.animation is None:
                return self.fill.color
            return self.animation.color_at(frame, default_color=self.fill.color)
        return self.fill.anchor_color

    def _local_bounds(self) -> tuple[float, float, float, float]:
        if self.kind in {"rectangle", "circle"}:
            width, height = self.size
            return 0.0, 0.0, width, height

        xs = [x for x, _ in self.points] or [0.0]
        ys = [y for _, y in self.points] or [0.0]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)
        return min_x, min_y, max_x - min_x, max_y - min_y

    def _color_sampler(
        self, target: "Frame", frame_index: int, scale: int
    ) -> Callable[[float, float], Color]:
        if isinstance(self.fill, SolidFill):
            color = self.color_at(frame_index)

            def _solid_sampler(_: float, __: float) -> Color:
                return color

            return _solid_sampler

        min_x, min_y, width, height = self._local_bounds()
        position = self.position_at(frame_index)
        pos_x = position[0] * scale
        pos_y = position[1] * scale
        rotation = self.rotation_at(frame_index)
        cos_r = math.cos(-rotation)
        sin_r = math.sin(-rotation)

        def _gradient_sampler(x: float, y: float) -> Color:
            dx = x - pos_x
            dy = y - pos_y
            if rotation != 0:
                local_x = dx * cos_r - dy * sin_r
                local_y = dx * sin_r + dy * cos_r
            else:
                local_x, local_y = dx, dy
            local_x /= scale
            local_y /= scale
            u = 0.0 if width == 0 else (local_x - min_x) / width
            v = 0.0 if height == 0 else (local_y - min_y) / height
            return self.fill.sample(
                u, v, texture_cache=_TEXTURE_CACHE, color_space=target.color_space
            )

        return _gradient_sampler

    def _frame_transform(self, frame: int) -> tuple[tuple[float, float], float]:
        """Return the position and rotation for ``frame``."""

        if self.animation is None:
            return self.position, self.rotation
        x, y, rotation = self.animation.transform_at(frame)
        return (x, y), rotation

    def render(self, target: "Frame", frame_index: int, *, scale: int = 1) -> None:
        """Draw the object on ``target``."""

        if self.kind == "rectangle":
            self._render_rectangle(target, frame_index, scale)
        elif self.kind == "circle":
            self._render_circle(target, frame_index, scale)
        elif self.kind == "line":
            self._render_line(target, frame_index, scale)
        elif self.kind == "polygon":
            self._render_polygon(target, frame_index, scale)
        else:  # pragma: no cover - defensive
            supported = ", ".join(SUPPORTED_OBJECT_TYPES)
            raise SceneError(
                f"Unsupported object type: {self.kind!r}. Supported types are: {supported}"
            )

    def _render_rectangle(self, target: "Frame", frame_index: int, scale: int) -> None:
        origin, rotation = self._frame_transform(frame_index)
        width, height = (value * scale for value in self.size)
        scaled_origin = (origin[0] * scale, origin[1] * scale)
        corners = ((0.0, 0.0), (width, 0.0), (width, height), (0.0, height))
        points = self._rotate_and_translate_points(
            corners, scaled_origin, rotation, scale=scale
        )

        sampler = self._color_sampler(target, frame_index, scale)
        self._fill_polygon(target, points, sampler)

        _, stroke_width = self._stroke_details(frame_index, scale)
        if stroke_width > 0:
            for index, start in enumerate(points):
                end = points[(index + 1) % len(points)]
                self._draw_line(target, start, end, frame_index, scale)

    def _render_circle(self, target: "Frame", frame_index: int, scale: int) -> None:
        position = self.position_at(frame_index)
        width, height = (value * scale for value in self.size)
        min_diameter = min(width, height)
        if min_diameter <= 0:
            raise SceneError(
                f"Circle '{self.id}' must have a positive diameter (got {width}x{height})"
            )

        radius = max(min_diameter / 2.0, 1.0)
        cx = position[0] * scale
        cy = position[1] * scale
        radius_sq = radius * radius

        sampler = self._color_sampler(target, frame_index, scale)

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
                    target._blend_into(row, x, sampler(x + 0.5, y + 0.5))

        stroke_color, stroke_width = self._stroke_details(frame_index, scale)
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
                    target,
                    start,
                    end,
                    frame_index,
                    scale,
                    stroke_color=stroke_color,
                )

    def _stroke_details(self, frame_index: int, scale: int) -> tuple[Color, int]:
        stroke_color = self.stroke_color or self.color_at(frame_index)
        stroke_width_value = 1.0 if self.stroke_width is None else self.stroke_width
        stroke_width = max(0, int(round(stroke_width_value * scale)))
        return stroke_color, stroke_width

    def _rotate_and_translate_points(
        self,
        points: Sequence[tuple[float, float]],
        origin: tuple[float, float],
        rotation: float,
        *,
        scale: float = 1.0,
    ) -> list[tuple[float, float]]:
        origin_x, origin_y = origin
        if rotation == 0:
            return [(x * scale + origin_x, y * scale + origin_y) for x, y in points]

        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        rotated = []
        for x, y in points:
            sx = x * scale
            sy = y * scale
            rx = sx * cos_r - sy * sin_r
            ry = sx * sin_r + sy * cos_r
            rotated.append((rx + origin_x, ry + origin_y))
        return rotated

    def _transformed_points(
        self, frame_index: int, scale: float
    ) -> list[tuple[float, float]]:
        origin, rotation = self._frame_transform(frame_index)
        scaled_origin = (origin[0] * scale, origin[1] * scale)
        return self._rotate_and_translate_points(
            self.points, scaled_origin, rotation, scale=scale
        )

    def _draw_point(
        self, target: "Frame", x: float, y: float, stroke_width: int, color: Color
    ) -> None:
        _draw_stroke_point(target, x, y, stroke_width, color)

    def _draw_line(
        self,
        target: "Frame",
        start: tuple[float, float],
        end: tuple[float, float],
        frame_index: int,
        scale: int,
        *,
        stroke_color: Color | None = None,
    ) -> None:
        stroke_color_value, stroke_width = self._stroke_details(frame_index, scale)
        resolved_stroke_color = stroke_color or stroke_color_value
        _draw_stroke_line(target, start, end, stroke_width, resolved_stroke_color)

    def _render_line(self, target: "Frame", frame_index: int, scale: int) -> None:
        points = self._transformed_points(frame_index, scale)
        self._draw_line(target, points[0], points[1], frame_index, scale)

    def _render_polygon(self, target: "Frame", frame_index: int, scale: int) -> None:
        points = self._transformed_points(frame_index, scale)
        if len(points) < 3:
            raise SceneError("Polygon must contain at least three points")

        sampler = self._color_sampler(target, frame_index, scale)
        self._fill_polygon(target, points, sampler)

        stroke_color, stroke_width = self._stroke_details(frame_index, scale)
        if stroke_width > 0:
            for i, start in enumerate(points):
                end = points[(i + 1) % len(points)]
                self._draw_line(
                    target, start, end, frame_index, scale, stroke_color=stroke_color
                )

    def _fill_polygon(
        self,
        target: "Frame",
        points: Sequence[tuple[float, float]],
        sampler: Callable[[float, float], Color],
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
                    target._blend_into(row, x, sampler(x + 0.5, y + 0.5))


@dataclass(slots=True)
class Scene:
    """Representation of a renderable scene."""

    width: int
    height: int
    frame_count: int
    background: Color
    backplate: Backplate | None = None
    color_space: ColorSpace = ColorSpace.SRGB
    objects: list[SceneObject] = field(default_factory=list)
    camera: CameraSettings = field(default_factory=CameraSettings)
    _render_transform: RenderTransform | None = field(
        default=None, init=False, repr=False
    )
    _color_manager: OcioConfig | None = field(default=None, init=False, repr=False)

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

        color_space = ColorSpace.from_value(
            payload.get("color_space", ColorSpace.SRGB.value)
        )

        backplate = _parse_backplate(payload.get("backplate"), color_space=color_space)

        objects_data = payload.get("objects", [])
        if not isinstance(objects_data, Sequence):
            raise SceneError("Scene objects must be supplied as a sequence")

        objects: list[SceneObject] = []
        seen_ids: set[str] = set()
        for index, obj in enumerate(objects_data):
            if not isinstance(obj, Mapping):
                raise SceneError(f"Scene object at index {index} must be a mapping")
            scene_object = SceneObject.from_dict(dict(obj), frame_count=frame_count)
            if scene_object.id in seen_ids:
                raise SceneError(
                    f"Scene object ids must be unique (duplicate id {scene_object.id!r})"
                )
            seen_ids.add(scene_object.id)
            objects.append(scene_object)

        objects.sort(key=lambda obj: obj.z_index)

        camera = CameraSettings.from_dict(payload.get("camera"))

        return cls(
            width=width,
            height=height,
            frame_count=frame_count,
            background=background,
            backplate=backplate,
            color_space=color_space,
            objects=objects,
            camera=camera,
        )

    def _transform_animation(
        self, animation: Animation | None, transform: RenderTransform
    ) -> Animation | None:
        if animation is None:
            return None

        transformed_keyframes: list[Keyframe] = []
        for keyframe in animation.keyframes:
            transformed_point = transform.apply_point((keyframe.x, keyframe.y))
            transformed_keyframes.append(
                Keyframe(
                    frame=keyframe.frame,
                    x=transformed_point[0],
                    y=transformed_point[1],
                    rotation=keyframe.rotation,
                    color=keyframe.color,
                    easing=keyframe.easing,
                )
            )

        return Animation(
            keyframes=transformed_keyframes, default_easing=animation.default_easing
        )

    def _apply_transform(
        self, transform: RenderTransform, *, render_width: int, render_height: int
    ) -> "Scene":
        transformed_objects: list[SceneObject] = []

        for obj in self.objects:
            if not isinstance(obj, SceneObject):
                transformed_objects.append(obj)
                continue
            transformed_objects.append(
                SceneObject(
                    id=obj.id,
                    kind=obj.kind,
                    color=obj.color,
                    fill=obj.fill,
                    position=transform.apply_point(obj.position),
                    size=transform.apply_size(obj.size),
                    rotation=obj.rotation,
                    z_index=obj.z_index,
                    points=tuple(transform.apply_point(point) for point in obj.points),
                    stroke_color=obj.stroke_color,
                    stroke_width=(
                        obj.stroke_width * transform.stroke_scale
                        if obj.stroke_width is not None
                        else None
                    ),
                    start_frame=obj.start_frame,
                    end_frame=obj.end_frame,
                    visibility=obj.visibility,
                    animation=self._transform_animation(obj.animation, transform),
                )
            )

        transformed_scene = Scene(
            width=render_width,
            height=render_height,
            frame_count=self.frame_count,
            background=self.background,
            backplate=self.backplate,
            color_space=self.color_space,
            objects=transformed_objects,
            camera=self.camera,
        )
        transformed_scene._render_transform = transform
        transformed_scene._color_manager = self._color_manager
        return transformed_scene

    def rasterized(self) -> "Scene":
        transform, render_width, render_height = self.camera.build_transform(
            self.width, self.height
        )
        return self._apply_transform(
            transform, render_width=render_width, render_height=render_height
        )


@dataclass(slots=True)
class Frame:
    """A single rendered image frame."""

    index: int
    width: int
    height: int
    pixels: list[list[Color]]
    color_space: ColorSpace = ColorSpace.SRGB
    has_alpha: bool | None = field(default=None, repr=False)
    guides: list[list[Color]] | None = None
    color_manager: OcioConfig | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.has_alpha is None:
            self.has_alpha = any(
                len(pixel) >= 4 for row in self.pixels for pixel in row
            )

    def _update_alpha_flag(self, pixel: Color) -> None:
        if self.has_alpha is not True and len(pixel) >= 4:
            self.has_alpha = True

    def _blend_into(self, row: list[Color], x: int, color: Color) -> None:
        blended = _blend_colors(row[x], color, color_space=self.color_space)
        row[x] = blended
        self._update_alpha_flag(blended)

    @classmethod
    def blank(
        cls,
        index: int,
        width: int,
        height: int,
        color: Color,
        *,
        color_space: ColorSpace = ColorSpace.SRGB,
        color_manager: OcioConfig | None = None,
    ) -> "Frame":
        """Create a blank frame filled with ``color``."""

        pixels = [[color for _ in range(width)] for _ in range(height)]
        return cls(
            index=index,
            width=width,
            height=height,
            pixels=pixels,
            color_space=color_space,
            has_alpha=len(color) >= 4,
            guides=None,
            color_manager=color_manager,
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

    def apply_overlay(self, overlay: "Frame") -> None:
        """Composite ``overlay`` onto this frame in-place."""

        if overlay.width != self.width or overlay.height != self.height:
            raise ValueError("Overlay dimensions must match the base frame")

        for y, row in enumerate(overlay.pixels):
            target_row = self.pixels[y]
            for x, pixel in enumerate(row):
                alpha = pixel[3] if len(pixel) >= 4 else 255
                if alpha == 0:
                    continue
                blended = _blend_colors(
                    target_row[x], pixel, color_space=self.color_space
                )
                target_row[x] = blended
                self._update_alpha_flag(blended)

    def downsample(self, factor: int, *, filter_name: str = "box") -> "Frame":
        """Return a version of the frame reduced by ``factor`` using ``filter``."""

        if factor <= 0:
            raise ValueError("Downsample factor must be greater than zero")
        if factor == 1:
            return self
        if self.width % factor != 0 or self.height % factor != 0:
            raise ValueError(
                "Downsample factor must evenly divide the frame dimensions"
            )

        normalized_filter = filter_name.lower()
        if normalized_filter not in {"box", "gaussian"}:
            raise ValueError("Downsample filter must be 'box' or 'gaussian'")

        include_alpha = self._has_alpha()
        if normalized_filter == "box":
            channels = 4 if include_alpha else 3
            out_width = self.width // factor
            out_height = self.height // factor
            pixels: list[list[Color]] = []
            for block_y in range(out_height):
                row: list[Color] = []
                y_start = block_y * factor
                for block_x in range(out_width):
                    x_start = block_x * factor
                    totals = [0, 0, 0, 0]
                    for yy in range(y_start, y_start + factor):
                        for xx in range(x_start, x_start + factor):
                            pixel = self.pixels[yy][xx]
                            r, g, b = pixel[:3]
                            totals[0] += r
                            totals[1] += g
                            totals[2] += b
                            totals[3] += pixel[3] if len(pixel) >= 4 else 255
                    divisor = factor * factor
                    averaged = [
                        int(round(component / divisor))
                        for component in totals[:channels]
                    ]
                    row.append(tuple(averaged))
                pixels.append(row)

            return Frame(
                index=self.index,
                width=out_width,
                height=out_height,
                pixels=pixels,
                color_space=self.color_space,
                has_alpha=include_alpha,
                color_manager=self.color_manager,
            )

        pillow = _require_pillow()
        mode = "RGBA" if include_alpha else "RGB"
        image = self.to_image(mode=mode, color_manager=self.color_manager)
        from PIL import ImageFilter as PILImageFilter  # imported lazily

        radius = max(factor / 2.0, 0.0)
        blurred = image.filter(PILImageFilter.GaussianBlur(radius=radius))
        resample = getattr(pillow, "Resampling", pillow)
        resized = blurred.resize(
            (self.width // factor, self.height // factor),
            resample=resample.BOX,
        )

        data = list(resized.getdata())
        resized_pixels: list[list[Color]] = []
        iterator = iter(data)
        for _ in range(resized.height):
            row = [tuple(next(iterator)) for _ in range(resized.width)]
            resized_pixels.append(row)

        return Frame(
            index=self.index,
            width=resized.width,
            height=resized.height,
            pixels=resized_pixels,
            color_space=self.color_space,
            has_alpha=include_alpha,
            color_manager=self.color_manager,
        )

    def save_ppm(self, destination: Path) -> None:
        """Write the frame to ``destination`` in the plain PPM format."""

        with destination.open("w", encoding="ascii") as stream:
            stream.write(f"P3\n{self.width} {self.height}\n255\n")
            if self.color_manager is None:
                for row in self.pixels:
                    values = " ".join("{} {} {}".format(*pixel[:3]) for pixel in row)
                    stream.write(values + "\n")
                return

            image = self.to_image(mode="RGB", color_manager=self.color_manager)
            data = list(image.getdata())
            iterator = iter(data)
            for _ in range(self.height):
                row_values = []
                for _ in range(self.width):
                    r, g, b = next(iterator)
                    row_values.append(f"{r} {g} {b}")
                stream.write(" ".join(row_values) + "\n")

    def to_image(
        self,
        *,
        mode: str | None = None,
        color_manager: OcioConfig | None = None,
    ) -> PILImage.Image:
        """Return the frame as a Pillow :class:`~PIL.Image.Image` instance."""

        pillow = _require_pillow()
        has_alpha = self._has_alpha()
        resolved_mode = mode or ("RGBA" if has_alpha else "RGB")
        if resolved_mode not in {"RGB", "RGBA"}:  # pragma: no cover - defensive
            raise ValueError(f"Unsupported image mode: {resolved_mode}")

        if color_manager is None:
            color_manager = self.color_manager

        if color_manager is None:
            data = self.to_bytes(mode=resolved_mode)
            pil_image: PILImage.Image = pillow.frombytes(
                resolved_mode, (self.width, self.height), data
            )
            return pil_image

        numpy = _require_numpy()
        buffer = self._float_buffer(
            color_manager=color_manager, apply_output_transform=True
        )
        scaled = numpy.clip(buffer * 255.0, 0.0, 255.0).astype(numpy.uint8)
        include_alpha = resolved_mode == "RGBA"
        channels = scaled[:, :, : (4 if include_alpha else 3)]
        transformed_image: PILImage.Image = pillow.fromarray(
            channels, mode=resolved_mode
        )
        return transformed_image

    def _float_buffer(
        self,
        *,
        dtype: Any = None,
        color_manager: OcioConfig | None = None,
        apply_output_transform: bool = False,
    ) -> Any:
        """Return a floating-point NumPy buffer of RGBA channels."""

        numpy = _require_numpy()
        buffer = numpy.zeros((self.height, self.width, 4), dtype=dtype or numpy.float32)

        for y, row in enumerate(self.pixels):
            for x, pixel in enumerate(row):
                r, g, b = pixel[:3]
                a = pixel[3] if len(pixel) >= 4 else 255
                buffer[y, x, 0] = _decode_component(r, self.color_space)
                buffer[y, x, 1] = _decode_component(g, self.color_space)
                buffer[y, x, 2] = _decode_component(b, self.color_space)
                buffer[y, x, 3] = max(0.0, min(255.0, float(a))) / 255.0

        if apply_output_transform and color_manager is not None:
            buffer = color_manager.apply_output_transform(buffer)

        return buffer

    def save_exr(
        self,
        destination: Path,
        *,
        bit_depth: str = "half",
        layers: set[str] | None = None,
    ) -> None:
        """Write the frame to ``destination`` as an OpenEXR file."""

        openexr, imath = _require_openexr()
        numpy = _require_numpy()

        normalized_layers = {
            layer.lower() for layer in (layers or {"beauty", "matte", "guides"})
        }
        allowed_layers = {"beauty", "matte", "guides"}
        if invalid := normalized_layers - allowed_layers:
            raise ValueError(f"Unsupported EXR layers requested: {sorted(invalid)}")

        normalized_bit_depth = bit_depth.lower()
        pixel_type = imath.PixelType(
            imath.PixelType.FLOAT
            if normalized_bit_depth == "float32"
            else imath.PixelType.HALF
        )
        dtype = numpy.float32 if normalized_bit_depth == "float32" else numpy.float16

        buffer = self._float_buffer(
            dtype=dtype,
            color_manager=self.color_manager,
            apply_output_transform=True,
        )

        header = openexr.Header(self.width, self.height)
        channels: dict[str, Any] = {}
        data: dict[str, bytes] = {}

        def _add_channel(name: str, array: Any) -> None:
            channels[name] = imath.Channel(pixel_type)
            data[name] = array.astype(dtype).tobytes()

        if "beauty" in normalized_layers:
            _add_channel("beauty.R", buffer[:, :, 0])
            _add_channel("beauty.G", buffer[:, :, 1])
            _add_channel("beauty.B", buffer[:, :, 2])
            _add_channel("beauty.A", buffer[:, :, 3])

        if "matte" in normalized_layers:
            _add_channel("matte.A", buffer[:, :, 3])

        if "guides" in normalized_layers and self.guides is not None:
            guides_frame = Frame(
                index=self.index,
                width=self.width,
                height=self.height,
                pixels=self.guides,
                color_space=self.color_space,
                has_alpha=True,
            )
            guides_buffer = guides_frame._float_buffer(dtype=dtype)
            _add_channel("guides.R", guides_buffer[:, :, 0])
            _add_channel("guides.G", guides_buffer[:, :, 1])
            _add_channel("guides.B", guides_buffer[:, :, 2])
            _add_channel("guides.A", guides_buffer[:, :, 3])

        header["channels"] = channels
        with openexr.OutputFile(str(destination), header) as stream:
            stream.writePixels(data)

    def save_dpx(
        self,
        destination: Path,
        *,
        bit_depth: str = "half",
        layers: set[str] | None = None,
    ) -> None:
        """Write the frame to ``destination`` as a DPX file."""

        del layers  # DPX currently writes a flattened image
        normalized_bit_depth = bit_depth.lower()
        numpy = _require_numpy()
        dtype = numpy.float32 if normalized_bit_depth == "float32" else numpy.float16
        buffer = self._float_buffer(
            dtype=dtype,
            color_manager=self.color_manager,
            apply_output_transform=True,
        )
        writer = _require_imageio()
        writer.imwrite(destination, buffer, extension=".dpx")

    def save_png(
        self, destination: Path, *, mode: str | None = None, **options: Any
    ) -> None:
        """Write the frame to ``destination`` as a PNG file."""

        image = self.to_image(mode=mode)
        metadata = _png_color_options(self.color_space)
        metadata.update(options)
        image.save(destination, format="PNG", **metadata)


class Renderer:
    """Render engine responsible for producing image frames."""

    def __init__(
        self,
        scene: Scene,
        *,
        samples: int = 1,
        filter_name: str = "box",
        guides: GuidesOverlay | None = None,
        ocio_config: Path | None = None,
        ocio_display: str | None = None,
        ocio_view: str | None = None,
    ):
        self.scene = scene
        if samples <= 0:
            raise SceneError("Supersampling 'samples' must be greater than zero")
        self.samples = samples
        normalized_filter = filter_name.lower()
        if normalized_filter not in {"box", "gaussian"}:
            raise SceneError("Downsample filter must be 'box' or 'gaussian'")
        self.filter = normalized_filter
        self.guides = guides
        self._ocio_config = (
            OcioConfig(path=ocio_config, display=ocio_display, view=ocio_view)
            if ocio_config is not None
            else None
        )
        if self._ocio_config is not None:
            self._apply_ocio_transforms()

        self._render_scene = self.scene.rasterized()
        self._render_transform = self._render_scene._render_transform
        self.scene._color_manager = self._ocio_config
        self._render_scene._color_manager = self._ocio_config

    def _attach_color_manager(self, frame: Frame) -> Frame:
        if self._ocio_config is not None:
            frame.color_manager = self._ocio_config
        return frame

    def _convert_color(self, color: Color, *, source_space: ColorSpace) -> Color:
        if self._ocio_config is None:
            return color
        return self._ocio_config.to_working(color, source_space=source_space)

    def _convert_fill_colors(self, fill: Fill, *, source_space: ColorSpace) -> None:
        if isinstance(fill, SolidFill):
            fill.color = self._convert_color(fill.color, source_space=source_space)
        elif isinstance(fill, LinearGradientFill):
            fill.start_color = self._convert_color(
                fill.start_color, source_space=source_space
            )
            fill.end_color = self._convert_color(
                fill.end_color, source_space=source_space
            )
        elif isinstance(fill, RadialGradientFill):
            fill.inner_color = self._convert_color(
                fill.inner_color, source_space=source_space
            )
            fill.outer_color = self._convert_color(
                fill.outer_color, source_space=source_space
            )

    def _apply_ocio_transforms(self) -> None:
        if self._ocio_config is None:
            return

        source_space = self.scene.color_space

        def convert(value: Color) -> Color:
            return self._convert_color(value, source_space=source_space)

        self.scene.background = convert(self.scene.background)

        for obj in self.scene.objects:
            if not isinstance(obj, SceneObject):
                continue
            obj.color = convert(obj.color)
            if obj.stroke_color is not None:
                obj.stroke_color = convert(obj.stroke_color)
            self._convert_fill_colors(obj.fill, source_space=source_space)
            if obj.animation is not None:
                for keyframe in obj.animation.keyframes:
                    if keyframe.color is not None:
                        keyframe.color = convert(keyframe.color)

        if self.guides is not None:
            self.guides.color = convert(self.guides.color)

        self.scene.color_space = ColorSpace.LINEAR

    def render(
        self,
        frames: Iterable[int] | None = None,
        *,
        workers: int | None = None,
        backend: str = "process",
    ) -> Iterator[Frame]:
        """Yield selected rendered frames lazily.

        Parameters
        ----------
        frames:
            Optional iterable of frame indices to render. If omitted, all frames in the
            scene will be produced.
        """

        if workers is not None and workers <= 0:
            raise SceneError("Worker count must be greater than zero when provided")

        backend_normalized = backend.lower()
        if backend_normalized not in {"process", "thread"}:
            raise SceneError("backend must be 'process' or 'thread'")

        target_scene = self._render_scene

        if frames is None:
            frame_indices = list(range(target_scene.frame_count))
        else:
            frame_indices = list(frames)
            if not frame_indices:
                raise SceneError("No frame indices were supplied for rendering")
            for index in frame_indices:
                if index < 0 or index >= target_scene.frame_count:
                    raise SceneError(
                        f"Frame index {index} is outside the 0-{target_scene.frame_count - 1} range"
                    )

        if workers is None or workers == 1 or len(frame_indices) <= 1:
            for index in frame_indices:
                frame = _render_frame_static(
                    target_scene, index, self.samples, self.filter, self.guides
                )
                yield self._attach_color_manager(frame)
            return

        executor_cls: type[Executor]
        if backend_normalized == "thread":
            if any(
                isinstance(getattr(obj, "fill", None), TextureFill)
                for obj in self.scene.objects
            ):
                raise SceneError(
                    "Threaded rendering is not supported for scenes using texture fills; "
                    "use process workers instead to isolate shared caches."
                )
            executor_cls = ThreadPoolExecutor
        else:
            executor_cls = ProcessPoolExecutor

        with executor_cls(max_workers=workers) as executor:  # type: ignore[call-arg]
            results = executor.map(
                _render_frame_static,
                itertools.repeat(target_scene),
                frame_indices,
                itertools.repeat(self.samples),
                itertools.repeat(self.filter),
                itertools.repeat(self.guides),
            )

            for frame in results:
                yield self._attach_color_manager(frame)


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
        first_image = first.to_image(mode="RGBA")
        frame_count = 1

        def _image_stream() -> Iterator[Any]:
            nonlocal frame_count
            for frame in rest:
                frame_count += 1
                yield frame.to_image(mode="RGBA")

        duration = (
            duration_ms
            if duration_ms is not None
            else max(int(round(1000 / self.fps)), 1)
        )
        first_image.save(
            destination,
            format="GIF",
            save_all=True,
            append_images=_image_stream(),
            duration=duration,
            loop=loop,
            disposal=2,
            optimize=optimize,
        )

        return frame_count

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
    "ColorSpace",
    "Frame",
    "GuidesOverlay",
    "Backplate",
    "Keyframe",
    "Renderer",
    "Scene",
    "SceneError",
    "SceneObject",
    "CameraSettings",
    "parse_color",
]
