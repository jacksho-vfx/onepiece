"""Typer command-line interface for the Chopper renderer."""

from __future__ import annotations

import csv
import json
import tempfile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

import click
from click.core import ParameterSource
from PIL import Image
import typer

from apps.chopper.renderer import (
    Color,
    ColorSpace,
    GuidesOverlay,
    Scene,
    SceneError,
    parse_color,
)
from libraries.automation.render.chopper import (
    ChopperRenderError,
    load_scene,
    render_scene,
)


app = typer.Typer(help="Render self-contained scene descriptions using Chopper.")


def _was_option_explicit(option_name: str) -> bool:
    try:
        ctx = click.get_current_context(silent=True)
    except RuntimeError:  # pragma: no cover - defensive
        return False

    if ctx is None:
        return False

    try:
        source = ctx.get_parameter_source(option_name)
    except (AttributeError, KeyError):  # pragma: no cover - defensive
        return False

    return source not in (None, ParameterSource.DEFAULT)


def _build_guides_overlay(
    *,
    safe_frame: bool,
    action_frame: bool,
    thirds_grid: bool,
    center_mark: bool,
    guides_color: str,
    guides_opacity: float,
    guides_width: float,
    action_ratio: float | None = None,
    safe_ratio: float | None = None,
) -> GuidesOverlay | None:
    guides_enabled = any((safe_frame, action_frame, thirds_grid, center_mark))
    if not guides_enabled:
        return None

    if guides_opacity < 0 or guides_opacity > 1:
        raise typer.BadParameter("guides-opacity must be within the 0-1 range")
    if guides_width <= 0:
        raise typer.BadParameter("guides-width must be greater than zero")

    try:
        overlay_color = parse_color(guides_color)
    except SceneError as exc:
        raise typer.BadParameter(str(exc)) from exc

    overlay = GuidesOverlay(
        safe_frame=safe_frame,
        action_frame=action_frame,
        thirds_grid=thirds_grid,
        center_mark=center_mark,
        color=overlay_color,
        opacity=guides_opacity,
        stroke_width=guides_width,
    )

    if action_ratio is not None:
        overlay.action_ratio = action_ratio
    if safe_ratio is not None:
        overlay.safe_ratio = safe_ratio

    return overlay


def _parse_window_option(value: str | None, label: str) -> tuple[float, float] | None:
    if value is None:
        return None
    parts = re.split(r"[x,]", value)
    if len(parts) != 2:
        raise typer.BadParameter(
            f"{label} must contain width and height separated by 'x' or ','"
        )
    try:
        width = float(parts[0])
        height = float(parts[1])
    except ValueError as exc:
        raise typer.BadParameter(f"{label} values must be numeric") from exc
    if width <= 0 or height <= 0:
        raise typer.BadParameter(f"{label} values must be greater than zero")
    return width, height


QC_RESOLUTION_PRESETS: dict[str, tuple[int, int]] = {
    "hd-1080": (1920, 1080),
    "uhd-2160": (3840, 2160),
    "scope-2k": (2048, 858),
    "scope-4k": (4096, 1716),
    "square-1k": (1024, 1024),
    "vertical-1080": (1080, 1920),
}

ASPECT_PRESETS: dict[str, float] = {
    "16:9": 16 / 9,
    "4:3": 4 / 3,
    "1:1": 1.0,
    "2.39:1": 2.39,
    "9:16": 9 / 16,
}


def _parse_resolution_value(value: str) -> tuple[int, int]:
    match = re.match(r"^(?P<width>\d+)[xX](?P<height>\d+)$", value)
    if not match:
        raise typer.BadParameter(
            "Resolution must be formatted as WIDTHxHEIGHT (for example 1920x1080)"
        )
    width = int(match.group("width"))
    height = int(match.group("height"))
    if width <= 0 or height <= 0:
        raise typer.BadParameter(
            "Resolution width and height must be greater than zero"
        )
    return width, height


def _parse_aspect_value(value: str) -> float:
    if value in ASPECT_PRESETS:
        return ASPECT_PRESETS[value]

    ratio_match = re.match(
        r"^(?P<width>\d+(?:\.\d+)?):(?P<height>\d+(?:\.\d+)?)$", value
    )
    if ratio_match:
        width = float(ratio_match.group("width"))
        height = float(ratio_match.group("height"))
        if width <= 0 or height <= 0:
            raise typer.BadParameter("Aspect ratio parts must be greater than zero")
        return width / height

    available = ", ".join(sorted(ASPECT_PRESETS))
    raise typer.BadParameter(
        f"Unsupported aspect ratio {value!r}. Choose from presets: {available} or use W:H"
    )


def _load_qc_resolution_preset(name: str) -> tuple[int, int]:
    preset = QC_RESOLUTION_PRESETS.get(name.lower())
    if preset is None:
        available = ", ".join(sorted(QC_RESOLUTION_PRESETS))
        raise typer.BadParameter(
            f"Unknown QC resolution preset {name!r}. Choose from: {available}"
        )
    return preset


def _load_qc_scene_template(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - filesystem failures
        raise typer.BadParameter(f"Unable to read template at {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(
            f"Template at {path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise typer.BadParameter(
            "QC template must contain a JSON object at the top level"
        )
    return payload


def _build_qc_scene_payload(
    *,
    width: int = 1920,
    height: int = 1080,
    slate_text: str | None = None,
    timecode: str | None = None,
    include_studio_logo: bool = False,
) -> dict[str, Any]:
    top_band_height = max(1, height // 4)
    bar_colors = ["#ef4444", "#f59e0b", "#eab308", "#10b981", "#0ea5e9", "#6366f1"]
    bar_width = width / len(bar_colors)

    objects: list[dict[str, Any]] = [
        {
            "id": f"bar-{index}",
            "type": "rectangle",
            "position": [index * bar_width, 0],
            "size": [bar_width, top_band_height],
            "color": color,
        }
        for index, color in enumerate(bar_colors)
    ]

    slate_height = height * 0.22
    slate_top = height * 0.55
    slate_left = width * 0.08
    objects.extend(
        [
            {
                "id": "slate",
                "type": "rectangle",
                "position": [slate_left, slate_top],
                "size": [width * 0.84, slate_height],
                "color": "#111827",
                "stroke_color": "#e5e7eb",
                "stroke_width": 6,
            },
            {
                "id": "target-left",
                "type": "circle",
                "position": [width * 0.26, slate_top + slate_height / 2],
                "size": [height * 0.14, height * 0.14],
                "color": "#f87171",
                "stroke_color": "#0f172a",
                "stroke_width": 4,
            },
            {
                "id": "target-right",
                "type": "circle",
                "position": [width * 0.74, slate_top + slate_height / 2],
                "size": [height * 0.14, height * 0.14],
                "color": "#38bdf8",
                "stroke_color": "#0f172a",
                "stroke_width": 4,
            },
            {
                "id": "center-diamond",
                "type": "polygon",
                "points": [
                    [width * 0.5, slate_top - slate_height * 0.2],
                    [width * 0.6, slate_top + slate_height * 0.1],
                    [width * 0.5, slate_top + slate_height * 0.4],
                    [width * 0.4, slate_top + slate_height * 0.1],
                ],
                "color": "#fcd34d",
                "stroke_color": "#0f172a",
                "stroke_width": 5,
            },
            {
                "id": "diagonal",
                "type": "line",
                "points": [[0, 0], [width, height]],
                "color": "#f1f5f9",
                "stroke_width": 6,
            },
            {
                "id": "crosshairs",
                "type": "line",
                "points": [[width, 0], [0, height]],
                "color": "#94a3b8",
                "stroke_width": 4,
            },
        ]
    )

    if slate_text:
        objects.extend(
            [
                {
                    "id": "slate-text",
                    "type": "rectangle",
                    "position": [
                        slate_left + width * 0.05,
                        slate_top + slate_height * 0.25,
                    ],
                    "size": [width * 0.7, slate_height * 0.18],
                    "color": "#1f2937",
                    "stroke_color": "#f8fafc",
                    "stroke_width": 2,
                    "label": slate_text,
                },
                {
                    "id": "slate-subtitle",
                    "type": "rectangle",
                    "position": [
                        slate_left + width * 0.05,
                        slate_top + slate_height * 0.5,
                    ],
                    "size": [width * 0.6, slate_height * 0.12],
                    "color": "#0f172a",
                    "stroke_color": "#cbd5e1",
                    "stroke_width": 2,
                },
            ]
        )

    if timecode:
        objects.append(
            {
                "id": "timecode",
                "type": "rectangle",
                "position": [width * 0.33, slate_top + slate_height * 0.75],
                "size": [width * 0.34, slate_height * 0.14],
                "color": "#111827",
                "stroke_color": "#f97316",
                "stroke_width": 3,
                "label": timecode,
            }
        )

    if include_studio_logo:
        logo_size = min(width, height) * 0.08
        logo_left = width - logo_size * 1.5
        logo_top = height * 0.08
        objects.extend(
            [
                {
                    "id": "studio-logo",
                    "type": "circle",
                    "position": [logo_left, logo_top],
                    "size": [logo_size, logo_size],
                    "color": "#0ea5e9",
                    "stroke_color": "#e0f2fe",
                    "stroke_width": 4,
                },
                {
                    "id": "studio-logo-mark",
                    "type": "polygon",
                    "points": [
                        [logo_left + logo_size * 0.5, logo_top + logo_size * 0.15],
                        [logo_left + logo_size * 0.8, logo_top + logo_size * 0.5],
                        [logo_left + logo_size * 0.5, logo_top + logo_size * 0.85],
                        [logo_left + logo_size * 0.2, logo_top + logo_size * 0.5],
                    ],
                    "color": "#022c4e",
                    "stroke_color": "#0ea5e9",
                    "stroke_width": 3,
                },
            ]
        )

    return {
        "width": width,
        "height": height,
        "frames": 1,
        "background": "#0b1224",
        "objects": objects,
    }


def _load_scene(path: Path) -> Scene:
    """Compatibility wrapper that re-raises errors as :class:`typer.BadParameter`."""

    try:
        return load_scene(path)
    except ChopperRenderError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def inspect(
    scene: Path = typer.Argument(..., help="Path to the JSON scene description."),
) -> None:
    """Summarise a scene without rendering frames."""

    parsed = _load_scene(scene)

    typer.echo(f"Dimensions: {parsed.width}x{parsed.height}")
    typer.echo(f"Frames: {parsed.frame_count}")

    typer.echo("Objects:")
    if not parsed.objects:
        typer.echo("- none")
    else:
        for obj in parsed.objects:
            typer.echo(f"- {obj.id} ({obj.kind})")

    animated_objects = [obj for obj in parsed.objects if obj.animation]
    typer.echo("Animation spans:")
    if not animated_objects:
        typer.echo("- none")
    else:
        for obj in animated_objects:
            assert obj.animation is not None  # for type checkers
            start_frame = obj.animation.keyframes[0].frame
            end_frame = obj.animation.keyframes[-1].frame
            span = (
                f"{start_frame}"
                if start_frame == end_frame
                else f"{start_frame}-{end_frame}"
            )
            typer.echo(
                f"- {obj.id}: frames {span} ({len(obj.animation.keyframes)} keyframe(s))"
            )


@app.command()
def render(
    scene: Path = typer.Argument(..., help="Path to the JSON scene description."),
    output: Path = typer.Option(
        Path("frames"),
        "--output",
        "-o",
        help=("Directory for per-frame exports or file path for bundled animations."),
    ),
    export: str = typer.Option(
        "ppm",
        "--format",
        "-f",
        case_sensitive=False,
        help=(
            "Output format: 'ppm' for plain-text dumps, 'png' for per-frame PNGs,"
            " 'exr'/'dpx' for high-dynamic-range exports, or 'gif'/'mp4' for "
            "bundled animations."
        ),
    ),
    bit_depth: str = typer.Option(
        "half",
        "--bit-depth",
        case_sensitive=False,
        help="EXR/DPX channel depth: half or float32.",
    ),
    layers: str = typer.Option(
        "beauty,matte,guides",
        "--layers",
        help=("Comma-separated EXR/DPX layers to include (beauty, matte, guides)."),
    ),
    fps: int = typer.Option(
        24, help="Frames per second used when encoding animations."
    ),
    samples: int = typer.Option(
        1,
        "--samples",
        help="Supersampling factor applied before downsampling the final frame.",
    ),
    downsample_filter: str = typer.Option(
        "box",
        "--filter",
        case_sensitive=False,
        help="Downsample filter to apply after supersampling: box or gaussian.",
    ),
    background: str | None = typer.Option(
        None,
        "--background",
        "-b",
        help="Override the scene background colour using a hex value like '#112233'.",
    ),
    backplate: str | None = typer.Option(
        None,
        "--backplate",
        help=(
            "Path to a still image or template used as a backplate."
            " Templates can reference {frame} or {index} for frame numbering."
        ),
    ),
    backplate_start: int = typer.Option(
        0,
        "--backplate-start",
        help="Optional start index added to frame numbers when formatting backplates.",
    ),
    start: int | None = typer.Option(
        None,
        "--start",
        help="First frame index to render (defaults to the first frame).",
    ),
    end: int | None = typer.Option(
        None,
        "--end",
        help="Last frame index to render (defaults to the final frame).",
    ),
    frames: str | None = typer.Option(
        None,
        "--frames",
        help=(
            "Comma-separated list of specific frame indices to render; cannot be combined "
            "with --start/--end."
        ),
    ),
    safe_frame: bool = typer.Option(
        False, "--safe-frame", help="Draw a title-safe frame border overlay."
    ),
    action_frame: bool = typer.Option(
        False, "--action-frame", help="Draw an action-safe frame border overlay."
    ),
    thirds_grid: bool = typer.Option(
        False, "--thirds-grid", help="Overlay a rule-of-thirds grid."
    ),
    center_mark: bool = typer.Option(
        False, "--center-mark", help="Overlay a small crosshair at the frame centre."
    ),
    color_space: str | None = typer.Option(
        None,
        "--color-space",
        help="Colour space for interpreting inputs: srgb or linear.",
        case_sensitive=False,
    ),
    guides_color: str = typer.Option(
        "#ffffff", "--guides-color", help="Stroke colour to use for overlay guides."
    ),
    guides_opacity: float = typer.Option(
        0.5,
        "--guides-opacity",
        help="Overlay opacity in the 0-1 range (defaults to 0.5).",
    ),
    guides_width: float = typer.Option(
        1.0, "--guides-width", help="Stroke width in pixels for overlay guides."
    ),
    workers: int | None = typer.Option(
        None,
        "--workers",
        "-w",
        help="Optional number of worker processes/threads to render frames in parallel.",
    ),
    worker_backend: str = typer.Option(
        "process",
        "--worker-backend",
        case_sensitive=False,
        help="Worker type to use when --workers is provided: process or thread.",
    ),
    ocio_config: Path | None = typer.Option(
        None,
        "--ocio-config",
        help=("Optional path to an OCIO-style JSON config defining colour transforms."),
    ),
    ocio_display: str | None = typer.Option(
        None,
        "--ocio-display",
        help="Display name to use from the OCIO config when one is provided.",
    ),
    ocio_view: str | None = typer.Option(
        None,
        "--ocio-view",
        help="View name to use from the OCIO config when one is provided.",
    ),
    camera_profile: Path | None = typer.Option(
        None,
        "--camera-profile",
        help="Path to a JSON camera profile containing gate information.",
    ),
    pixel_aspect_ratio: float | None = typer.Option(
        None,
        "--pixel-aspect-ratio",
        help="Override the camera pixel aspect ratio.",
    ),
    horizontal_aperture: float | None = typer.Option(
        None,
        "--horizontal-aperture",
        help="Camera horizontal aperture size (e.g. in millimetres).",
    ),
    vertical_aperture: float | None = typer.Option(
        None,
        "--vertical-aperture",
        help="Camera vertical aperture size (e.g. in millimetres).",
    ),
    focal_length: float | None = typer.Option(
        None,
        "--focal-length",
        help="Camera focal length metadata used for framing calculations.",
    ),
    overscan: float | None = typer.Option(
        None,
        "--overscan",
        help=(
            "Fractional overscan to apply to the camera gate (e.g. 0.1 adds 10%"
            " padding)."
        ),
    ),
    active_window: str | None = typer.Option(
        None,
        "--active-window",
        help=("Active aperture width and height as 'width,height' or 'widthxheight'."),
    ),
    safe_window: str | None = typer.Option(
        None,
        "--safe-window",
        help="Safe aperture width and height as 'width,height' or 'widthxheight'.",
    ),
) -> None:
    """Render a scene description and write the frames to disk."""

    export_was_explicit = _was_option_explicit("export")
    background_override: Color | None = None
    frame_list: list[int] | None = None
    color_space_choice: ColorSpace | None = None
    guides_overlay: GuidesOverlay | None = None
    layer_set: set[str] | None = None
    active_window_tuple: tuple[float, float] | None = None
    safe_window_tuple: tuple[float, float] | None = None

    if background is not None:
        try:
            background_override = parse_color(background)
        except SceneError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if frames is not None:
        try:
            frame_list = _parse_frame_list(frames)
        except ValueError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if layers:
        raw_layers = [
            part.strip().lower() for part in layers.split(",") if part.strip()
        ]
        if not raw_layers:
            raise typer.BadParameter(
                "At least one layer must be provided when using --layers"
            )
        layer_set = set(raw_layers)

    if color_space is not None:
        try:
            color_space_choice = ColorSpace.from_value(color_space)
        except SceneError as exc:
            raise typer.BadParameter(str(exc)) from exc

    try:
        active_window_tuple = _parse_window_option(active_window, "active-window")
        safe_window_tuple = _parse_window_option(safe_window, "safe-window")
    except typer.BadParameter:
        raise

    guides_overlay = _build_guides_overlay(
        safe_frame=safe_frame,
        action_frame=action_frame,
        thirds_grid=thirds_grid,
        center_mark=center_mark,
        guides_color=guides_color,
        guides_opacity=guides_opacity,
        guides_width=guides_width,
    )

    try:
        message = render_scene(
            scene_path=scene,
            output_path=output,
            export_format=export,
            fps=fps,
            export_was_explicit=export_was_explicit,
            background_override=background_override,
            backplate_path=backplate,
            backplate_start=backplate_start,
            start_frame=start,
            end_frame=end,
            frames=frame_list,
            samples=samples,
            filter_name=downsample_filter,
            workers=workers,
            worker_backend=worker_backend,
            guides=guides_overlay,
            color_space=color_space_choice,
            bit_depth=bit_depth,
            layers=layer_set,
            camera_profile=camera_profile,
            pixel_aspect_ratio=pixel_aspect_ratio,
            horizontal_aperture=horizontal_aperture,
            vertical_aperture=vertical_aperture,
            focal_length=focal_length,
            overscan=overscan,
            active_window=active_window_tuple,
            safe_window=safe_window_tuple,
        )
    except ChopperRenderError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(message)


@app.command(name="qc-render")
def qc_render(
    output: Path = typer.Option(
        Path("qc_frames"),
        "--output",
        "-o",
        help="Directory for per-frame exports or file path for bundled animations.",
    ),
    export: str = typer.Option(
        "png",
        "--format",
        "-f",
        case_sensitive=False,
        help=(
            "Output format: 'ppm' for plain-text dumps, 'png' for per-frame PNGs,"
            " or 'gif'/'mp4' for bundled animations."
        ),
    ),
    fps: int = typer.Option(
        24, help="Frames per second used when encoding animations."
    ),
    samples: int = typer.Option(
        2,
        "--samples",
        help="Supersampling factor applied before downsampling the final frame.",
    ),
    downsample_filter: str = typer.Option(
        "box",
        "--filter",
        case_sensitive=False,
        help="Downsample filter to apply after supersampling: box or gaussian.",
    ),
    safe_frame: bool = typer.Option(
        False, "--safe-frame", help="Draw a title-safe frame border overlay."
    ),
    action_frame: bool = typer.Option(
        False, "--action-frame", help="Draw an action-safe frame border overlay."
    ),
    thirds_grid: bool = typer.Option(
        False, "--thirds-grid", help="Overlay a rule-of-thirds grid."
    ),
    center_mark: bool = typer.Option(
        False, "--center-mark", help="Overlay a small crosshair at the frame centre."
    ),
    guides_color: str = typer.Option(
        "#ffffff", "--guides-color", help="Stroke colour to use for overlay guides."
    ),
    guides_opacity: float = typer.Option(
        0.5,
        "--guides-opacity",
        help="Overlay opacity in the 0-1 range (defaults to 0.5).",
    ),
    guides_width: float = typer.Option(
        1.0, "--guides-width", help="Stroke width in pixels for overlay guides."
    ),
    workers: int | None = typer.Option(
        None,
        "--workers",
        "-w",
        help="Optional number of worker processes/threads to render frames in parallel.",
    ),
    worker_backend: str = typer.Option(
        "process",
        "--worker-backend",
        case_sensitive=False,
        help="Worker type to use when --workers is provided: process or thread.",
    ),
    color_space: str | None = typer.Option(
        None,
        "--color-space",
        help="Colour space for interpreting inputs: srgb or linear.",
        case_sensitive=False,
    ),
    ocio_config: Path | None = typer.Option(
        None,
        "--ocio-config",
        help="Optional path to an OCIO-style JSON config defining colour transforms.",
    ),
    ocio_display: str | None = typer.Option(
        None,
        "--ocio-display",
        help="Display name to use from the OCIO config when one is provided.",
    ),
    ocio_view: str | None = typer.Option(
        None,
        "--ocio-view",
        help="View name to use from the OCIO config when one is provided.",
    ),
    camera_profile: Path | None = typer.Option(
        None,
        "--camera-profile",
        help="Optional JSON file describing camera gate settings.",
    ),
    pixel_aspect_ratio: float | None = typer.Option(
        None,
        "--pixel-aspect-ratio",
        help="Override the camera pixel aspect ratio for QC renders.",
    ),
    horizontal_aperture: float | None = typer.Option(
        None,
        "--horizontal-aperture",
        help="Camera horizontal aperture size (e.g. in millimetres).",
    ),
    vertical_aperture: float | None = typer.Option(
        None,
        "--vertical-aperture",
        help="Camera vertical aperture size (e.g. in millimetres).",
    ),
    focal_length: float | None = typer.Option(
        None,
        "--focal-length",
        help="Camera focal length metadata used for framing calculations.",
    ),
    overscan: float | None = typer.Option(
        None,
        "--overscan",
        help="Fractional overscan padding applied around the render gate.",
    ),
    active_window: str | None = typer.Option(
        None,
        "--active-window",
        help=("Active aperture width and height as 'width,height' or 'widthxheight'."),
    ),
    safe_window: str | None = typer.Option(
        None,
        "--safe-window",
        help="Safe aperture width and height as 'width,height' or 'widthxheight'.",
    ),
    preset: str = typer.Option(
        "hd-1080",
        "--preset",
        "-p",
        help=(
            "QC resolution preset to use when building the scene. Presets: "
            + ", ".join(sorted(QC_RESOLUTION_PRESETS))
        ),
    ),
    resolution: str | None = typer.Option(
        None,
        "--resolution",
        "-r",
        help="Explicit resolution override as WIDTHxHEIGHT (overrides --preset).",
    ),
    aspect: str | None = typer.Option(
        None,
        "--aspect",
        help=(
            "Optional aspect ratio preset (e.g. 16:9, 4:3, 2.39:1, 9:16) "
            "or custom W:H ratio."
        ),
    ),
    slate_text: str | None = typer.Option(
        None,
        "--slate-text",
        help="Add labelled slate bars to the QC scene with the provided text.",
    ),
    timecode: str | None = typer.Option(
        None,
        "--timecode",
        help="Overlay a simple timecode bar with the supplied timecode string.",
    ),
    studio_logo: bool = typer.Option(
        False,
        "--studio-logo/--no-studio-logo",
        help="Toggle a simple studio logo mark in the QC scene.",
    ),
    template: Path | None = typer.Option(
        None,
        "--template",
        help="Load a QC template JSON file instead of the built-in payload.",
    ),
    save_template: Path | None = typer.Option(
        None,
        "--save-template",
        help="Write the QC template used for rendering to this path.",
    ),
) -> None:
    """Render a built-in QC scene without providing an input file."""

    export_was_explicit = _was_option_explicit("export")
    guides_overlay = _build_guides_overlay(
        safe_frame=safe_frame,
        action_frame=action_frame,
        thirds_grid=thirds_grid,
        center_mark=center_mark,
        guides_color=guides_color,
        guides_opacity=guides_opacity,
        guides_width=guides_width,
    )

    color_space_choice: ColorSpace | None = None
    active_window_tuple = _parse_window_option(active_window, "active-window")
    safe_window_tuple = _parse_window_option(safe_window, "safe-window")
    if color_space is not None:
        try:
            color_space_choice = ColorSpace.from_value(color_space)
        except SceneError as exc:
            raise typer.BadParameter(str(exc)) from exc

    if template is not None:
        qc_scene_payload = _load_qc_scene_template(template)
    else:
        width, height = _load_qc_resolution_preset(preset)
        if resolution:
            width, height = _parse_resolution_value(resolution)
        if aspect:
            aspect_ratio = _parse_aspect_value(aspect)
            height = max(1, int(round(width / aspect_ratio)))

        qc_scene_payload = _build_qc_scene_payload(
            width=width,
            height=height,
            slate_text=slate_text,
            timecode=timecode,
            include_studio_logo=studio_logo,
        )

    if save_template:
        save_template.write_text(
            json.dumps(qc_scene_payload, indent=2), encoding="utf-8"
        )

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            scene_path = Path(temp_dir) / "qc_scene.json"
            scene_path.write_text(json.dumps(qc_scene_payload), encoding="utf-8")

            message = render_scene(
                scene_path=scene_path,
                output_path=output,
                export_format=export,
                fps=fps,
                export_was_explicit=export_was_explicit,
                samples=samples,
                filter_name=downsample_filter,
                workers=workers,
                worker_backend=worker_backend,
                guides=guides_overlay,
                color_space=color_space_choice,
                ocio_config=ocio_config,
                ocio_display=ocio_display,
                ocio_view=ocio_view,
                camera_profile=camera_profile,
                pixel_aspect_ratio=pixel_aspect_ratio,
                horizontal_aperture=horizontal_aperture,
                vertical_aperture=vertical_aperture,
                focal_length=focal_length,
                overscan=overscan,
                active_window=active_window_tuple,
                safe_window=safe_window_tuple,
            )
    except ChopperRenderError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(message)


@app.command()
def compare(
    first: Path = typer.Argument(
        ..., help="Path to the first scene file or frame directory."
    ),
    second: Path = typer.Argument(
        ..., help="Path to the second scene file or frame directory."
    ),
    output: Path = typer.Option(
        Path("diff"),
        "--output",
        "-o",
        help="Directory where per-frame difference images will be written.",
    ),
    report_format: list[str] = typer.Option(
        default_factory=list,
        help=(
            "Optional report formats (json, csv, html) to generate alongside diff "
            "images. Use multiple times to request more than one format."
        ),
        case_sensitive=False,
    ),
) -> None:
    """Render and compare two scenes or directories of frames."""

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        try:
            first_frames = _prepare_frames(first, temp_root / "first")
            second_frames = _prepare_frames(second, temp_root / "second")
        except ChopperRenderError as exc:
            raise typer.BadParameter(str(exc)) from exc

        first_list = _collect_frames(first_frames)
        second_list = _collect_frames(second_frames)

        if len(first_list) != len(second_list):
            raise typer.BadParameter(
                "Frame directories must contain the same number of frames"
            )

        output.mkdir(parents=True, exist_ok=True)

        report_formats = _normalize_report_formats(report_format)

        total_delta = 0.0
        total_pixels = 0
        overall_max = 0.0
        frame_stats: list[_FrameResult] = []

        for left, right in zip(first_list, second_list):
            if left.name != right.name:
                raise typer.BadParameter("Frame names must match between directories")

            diff_result = _write_diff(left, right, output)
            frame_pixels = diff_result.stats.pixel_count
            total_delta += diff_result.stats.total_delta
            total_pixels += frame_pixels
            overall_max = max(overall_max, diff_result.stats.max_delta)
            frame_stats.append(diff_result)

            typer.echo(
                f"{left.name}: mean delta {diff_result.stats.mean_delta:.2f}, "
                f"max delta {diff_result.stats.max_delta:.2f}"
            )

        overall_mean = total_delta / total_pixels if total_pixels else 0.0
        typer.echo(
            f"Overall: mean delta {overall_mean:.2f}, max delta {overall_max:.2f}"
        )

        if report_formats:
            report_payload = _build_report_payload(
                first,
                second,
                output,
                frame_stats,
                overall_mean,
                overall_max,
                total_pixels,
            )
            _write_reports(report_payload, report_formats)


def _parse_frame_list(raw: str) -> list[int]:
    values = [part.strip() for part in raw.split(",") if part.strip()]
    if not values:
        raise ValueError("Frame list cannot be empty")

    indices: list[int] = []
    for value in values:
        try:
            indices.append(int(value))
        except ValueError as exc:
            raise ValueError(f"Frame value {value!r} is not an integer") from exc

    return indices


def _prepare_frames(source: Path, destination: Path) -> Path:
    if source.is_dir():
        return source

    render_scene(
        scene_path=source,
        output_path=destination,
        export_format="png",
        fps=24,
        export_was_explicit=True,
    )
    return destination


def _collect_frames(directory: Path) -> list[Path]:
    frames = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in {".png", ".ppm"}
    )

    if not frames:
        raise ChopperRenderError(f"No frames found in {directory}")

    return frames


class _DiffStats:
    def __init__(self, mean_delta: float, max_delta: float, pixel_count: int):
        self.mean_delta = mean_delta
        self.max_delta = max_delta
        self.total_delta = mean_delta * pixel_count
        self.pixel_count = pixel_count


class _FrameResult:
    def __init__(self, name: str, stats: _DiffStats, diff_path: Path):
        self.name = name
        self.stats = stats
        self.diff_path = diff_path


def _write_diff(left: Path, right: Path, output_dir: Path) -> _FrameResult:
    left_image = Image.open(left).convert("RGB")
    right_image = Image.open(right).convert("RGB")

    if left_image.size != right_image.size:
        raise ChopperRenderError("Frames must share the same dimensions")

    left_array = np.asarray(left_image, dtype=np.int16)
    right_array = np.asarray(right_image, dtype=np.int16)
    delta = np.abs(left_array - right_array)

    mean_delta = float(delta.mean())
    max_delta = float(delta.max(initial=0))

    diff_path = output_dir / f"{left.stem}_diff.png"
    diff_image = Image.fromarray(delta.astype(np.uint8), mode="RGB")
    diff_image.save(diff_path)

    pixel_count = int(delta.size)
    stats = _DiffStats(mean_delta, max_delta, pixel_count)
    return _FrameResult(left.stem, stats, diff_path)


def _normalize_report_formats(values: Sequence[str]) -> list[str]:
    supported = {"json", "csv", "html"}
    normalized: list[str] = []
    for value in values:
        lower = value.lower()
        if lower not in supported:
            raise typer.BadParameter(
                f"Unsupported report format {value!r}. Choose from json, csv, html."
            )
        if lower not in normalized:
            normalized.append(lower)
    return normalized


def _build_report_payload(
    first: Path,
    second: Path,
    output: Path,
    frame_results: Iterable[_FrameResult],
    overall_mean: float,
    overall_max: float,
    total_pixels: int,
) -> dict[str, Any]:
    frames = [
        {
            "frame": result.name,
            "mean_delta": result.stats.mean_delta,
            "max_delta": result.stats.max_delta,
            "pixel_count": result.stats.pixel_count,
            "total_delta": result.stats.total_delta,
            "diff_image": str(output.joinpath(result.diff_path.name)),
        }
        for result in frame_results
    ]

    status = "pass" if overall_max == 0 else "fail"
    timestamp = datetime.now(timezone.utc).isoformat()

    return {
        "metadata": {
            "timestamp": timestamp,
            "status": status,
            "output_directory": str(output),
            "first_source": str(first),
            "second_source": str(second),
        },
        "summary": {
            "overall_mean_delta": overall_mean,
            "overall_max_delta": overall_max,
            "total_pixels": total_pixels,
            "frame_count": len(frames),
        },
        "frames": frames,
    }


def _write_reports(payload: dict[str, Any], formats: Iterable[str]) -> None:
    for report_format in formats:
        if report_format == "json":
            _write_json_report(payload)
        elif report_format == "csv":
            _write_csv_report(payload)
        elif report_format == "html":
            _write_html_report(payload)


def _write_json_report(payload: dict[str, Any]) -> None:
    output_path = (
        Path(payload["metadata"]["output_directory"]) / "comparison_report.json"
    )
    with output_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)


def _write_csv_report(payload: dict[str, Any]) -> None:
    output_path = (
        Path(payload["metadata"]["output_directory"]) / "comparison_report.csv"
    )
    fieldnames = [
        "frame",
        "mean_delta",
        "max_delta",
        "pixel_count",
        "total_delta",
        "diff_image",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(payload["frames"])


def _write_html_report(payload: dict[str, Any]) -> None:
    output_path = (
        Path(payload["metadata"]["output_directory"]) / "comparison_report.html"
    )
    frame_rows = "\n".join(
        (
            "<tr>"
            f"<td>{frame['frame']}</td>"
            f"<td>{frame['mean_delta']:.2f}</td>"
            f"<td>{frame['max_delta']:.2f}</td>"
            f"<td>{frame['pixel_count']}</td>"
            f"<td>{frame['total_delta']:.2f}</td>"
            f"<td>{frame['diff_image']}</td>"
            "</tr>"
        )
        for frame in payload["frames"]
    )

    metadata = payload["metadata"]
    summary = payload["summary"]
    html_content = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\">
  <title>Chopper Comparison Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 1.5rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f4f4f4; }}
  </style>
</head>
<body>
  <h1>Chopper Comparison Report</h1>
  <p><strong>Status:</strong> {metadata['status']}</p>
  <p><strong>Timestamp:</strong> {metadata['timestamp']}</p>
  <p><strong>First source:</strong> {metadata['first_source']}<br>
     <strong>Second source:</strong> {metadata['second_source']}</p>
  <h2>Summary</h2>
  <ul>
    <li>Overall mean delta: {summary['overall_mean_delta']:.2f}</li>
    <li>Overall max delta: {summary['overall_max_delta']:.2f}</li>
    <li>Total pixels: {summary['total_pixels']}</li>
    <li>Frame count: {summary['frame_count']}</li>
  </ul>
  <h2>Frames</h2>
  <table>
    <thead>
      <tr>
        <th>Frame</th>
        <th>Mean delta</th>
        <th>Max delta</th>
        <th>Pixel count</th>
        <th>Total delta</th>
        <th>Diff image</th>
      </tr>
    </thead>
    <tbody>
      {frame_rows}
    </tbody>
  </table>
</body>
</html>
"""

    output_path.write_text(html_content, encoding="utf-8")


__all__ = [
    "app",
    "inspect",
    "render",
    "compare",
    "_load_scene",
]
