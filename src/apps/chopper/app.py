"""Typer command-line interface for the Chopper renderer."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, cast

import boto3
import click
import numpy as np
import typer
from botocore.exceptions import ClientError
from click.core import ParameterSource
from PIL import Image

from apps.chopper.renderer import (
    Color,
    ColorSpace,
    GuidesOverlay,
    Scene,
    SceneError,
    parse_color,
)
from libraries.automation.ingest.uploaders import S3ClientProtocol
from libraries.automation.render import chopper as chopper_render
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


def _create_s3_client() -> S3ClientProtocol:
    client = boto3.client("s3")
    return cast(S3ClientProtocol, client)


def _resolve_export_destination(
    output: Path, export_format: str, export_was_explicit: bool
) -> tuple[Path, str]:
    normalized_export = chopper_render._normalize_export_format(  # type: ignore[attr-defined]
        output_path=output,
        export_format=export_format,
        export_was_explicit=export_was_explicit,
    )

    destination = output
    if normalized_export in {"gif", "mp4"}:
        suffix = f".{normalized_export}"
        if destination.suffix.lower() != suffix:
            destination = destination.with_suffix(suffix)

    return destination, normalized_export


def _iter_export_files(export_root: Path) -> Iterable[Path]:
    if export_root.is_file():
        yield export_root
        return
    if not export_root.is_dir():
        raise FileNotFoundError(f"Export path {export_root} was not created")

    for child in export_root.rglob("*"):
        if child.is_file():
            yield child


def _export_render_output_to_s3(
    export_root: Path,
    *,
    bucket: str,
    prefix: str | None,
    resume: bool,
    client: S3ClientProtocol | None = None,
) -> list[str]:
    s3_client = client or _create_s3_client()
    normalized_prefix = prefix.strip("/") if prefix else ""

    uploaded: list[str] = []
    for file_path in _iter_export_files(export_root):
        relative_key = (
            file_path.name
            if export_root.is_file()
            else file_path.relative_to(export_root).as_posix()
        )
        key = "/".join(part for part in (normalized_prefix, relative_key) if part)

        if resume:
            try:
                s3_client.head_object(Bucket=bucket, Key=key)
                continue
            except ClientError as exc:
                error_code = exc.response.get("Error", {}).get("Code")
                if error_code not in {"404", "NotFound", "NoSuchKey"}:
                    raise

        s3_client.upload_file(str(file_path), bucket, key)
        uploaded.append(key)

    return uploaded


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


@app.command()
def presets(
    format: str = typer.Option(
        "plain",
        "--format",
        "-f",
        case_sensitive=False,
        help="Output format: 'plain' for text or 'json' for structured output.",
    ),
) -> None:
    """List available QC resolution presets."""

    if not QC_RESOLUTION_PRESETS:
        typer.echo("No QC resolution presets are defined.", err=True)
        raise typer.Exit(code=1)

    normalized_format = format.lower()
    presets_list = sorted(QC_RESOLUTION_PRESETS.items())

    if normalized_format == "json":
        payload = [
            {"name": name, "width": width, "height": height}
            for name, (width, height) in presets_list
        ]
        typer.echo(json.dumps(payload, indent=2))
    elif normalized_format == "plain":
        for name, (width, height) in presets_list:
            typer.echo(f"{name}: {width}x{height}")
    else:
        available_formats = "plain, json"
        raise typer.BadParameter(
            f"Unsupported format {format!r}. Choose from: {available_formats}."
        )


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
    s3_bucket: str | None = typer.Option(
        None,
        "--s3-bucket",
        help="Optional S3 bucket to upload renders after completion.",
    ),
    s3_prefix: str | None = typer.Option(
        None,
        "--prefix",
        help="Prefix within the S3 bucket for uploaded renders.",
    ),
    s3_resume: bool = typer.Option(
        False,
        "--resume/--no-resume",
        help=("Skip uploading files that already exist at the same S3 key."),
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

    if s3_bucket:
        try:
            destination, _ = _resolve_export_destination(
                output, export, export_was_explicit
            )
            uploaded = _export_render_output_to_s3(
                destination,
                bucket=s3_bucket,
                prefix=s3_prefix,
                resume=s3_resume,
            )
        except Exception as exc:  # pragma: no cover - runtime safety
            raise typer.BadParameter(f"Failed to upload renders to S3: {exc}") from exc

        normalized_prefix = s3_prefix.strip("/") if s3_prefix else ""
        location = (
            f"s3://{s3_bucket}/{normalized_prefix}"
            if normalized_prefix
            else f"s3://{s3_bucket}"
        )
        if uploaded:
            typer.echo(f"Uploaded {len(uploaded)} file(s) to {location}")
        else:
            typer.echo(f"S3 export skipped; existing objects preserved at {location}")


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
    s3_bucket: str | None = typer.Option(
        None,
        "--s3-bucket",
        help="Optional S3 bucket to upload renders after completion.",
    ),
    s3_prefix: str | None = typer.Option(
        None,
        "--prefix",
        help="Prefix within the S3 bucket for uploaded renders.",
    ),
    s3_resume: bool = typer.Option(
        False,
        "--resume/--no-resume",
        help="Skip uploading files that already exist at the same S3 key.",
    ),
    preset: str = typer.Option(
        "hd-1080",
        "--preset",
        "-p",
        help=(
            "QC resolution preset to use when building the scene. Presets: "
            + ", ".join(sorted(QC_RESOLUTION_PRESETS))
            + ". Run 'chopper presets' to view details."
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
    save_scene: Path | None = typer.Option(
        None,
        "--save-scene",
        help="Write the generated QC scene JSON to this path before rendering.",
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

    if save_scene:
        save_scene.parent.mkdir(parents=True, exist_ok=True)
        save_scene.write_text(json.dumps(qc_scene_payload, indent=2), encoding="utf-8")

    scene_hash = _hash_scene_payload(qc_scene_payload)

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

    _write_qc_report(
        output,
        qc_scene_payload,
        scene_hash,
        scene_path=save_scene,
        export_format=export,
        fps=fps,
        samples=samples,
        filter_name=downsample_filter,
        workers=workers,
        worker_backend=worker_backend,
    )

    typer.echo(f"{message} (scene sha256: {scene_hash})")

    if s3_bucket:
        try:
            destination, _ = _resolve_export_destination(
                output, export, export_was_explicit
            )
            uploaded = _export_render_output_to_s3(
                destination,
                bucket=s3_bucket,
                prefix=s3_prefix,
                resume=s3_resume,
            )
        except Exception as exc:  # pragma: no cover - runtime safety
            raise typer.BadParameter(f"Failed to upload renders to S3: {exc}") from exc

        normalized_prefix = s3_prefix.strip("/") if s3_prefix else ""
        location = (
            f"s3://{s3_bucket}/{normalized_prefix}"
            if normalized_prefix
            else f"s3://{s3_bucket}"
        )
        if uploaded:
            typer.echo(f"Uploaded {len(uploaded)} file(s) to {location}")
        else:
            typer.echo(f"S3 export skipped; existing objects preserved at {location}")


@dataclass
class _ComparisonOutcome:
    first: Path
    second: Path
    output: Path
    frame_results: list[_FrameResult]
    overall_mean: float
    overall_max: float
    total_pixels: int
    failure_messages: list[str]

    @property
    def status(self) -> str:
        return "pass" if not self.failure_messages else "fail"


def _run_comparison(
    *,
    first: Path,
    second: Path,
    output: Path,
    report_formats: Sequence[str],
    mean_threshold: float | None,
    max_threshold: float | None,
    per_frame_mean_threshold: float | None,
    per_frame_max_threshold: float | None,
    echo: Callable[[str], None] | None = typer.echo,
    write_reports: bool = True,
) -> _ComparisonOutcome:
    echo_fn: Callable[[str], None] = echo or (lambda *_args, **_kwargs: None)
    normalized_formats = _normalize_report_formats(report_formats)

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        first_frames = _prepare_frames(first, temp_root / "first")
        second_frames = _prepare_frames(second, temp_root / "second")

        first_list = _collect_frames(first_frames)
        second_list = _collect_frames(second_frames)

        if len(first_list) != len(second_list):
            raise typer.BadParameter(
                "Frame directories must contain the same number of frames"
            )

        output.mkdir(parents=True, exist_ok=True)

        total_delta = 0.0
        total_pixels = 0
        overall_max = 0.0
        frame_stats: list[_FrameResult] = []
        failed_frames: list[_FrameResult] = []

        for left, right in zip(first_list, second_list):
            if left.name != right.name:
                raise typer.BadParameter("Frame names must match between directories")

            diff_result = _write_diff(left, right, output)
            _evaluate_frame_thresholds(
                diff_result, per_frame_mean_threshold, per_frame_max_threshold
            )
            frame_pixels = diff_result.stats.pixel_count
            total_delta += diff_result.stats.total_delta
            total_pixels += frame_pixels
            overall_max = max(overall_max, diff_result.stats.max_delta)
            frame_stats.append(diff_result)
            if diff_result.failures:
                failed_frames.append(diff_result)

            echo_fn(
                f"{left.name}: mean delta {diff_result.stats.mean_delta:.2f}, "
                f"max delta {diff_result.stats.max_delta:.2f}"
            )

        overall_mean = total_delta / total_pixels if total_pixels else 0.0
        echo_fn(f"Overall: mean delta {overall_mean:.2f}, max delta {overall_max:.2f}")

        failure_messages = _collect_failures(
            overall_mean=overall_mean,
            overall_max=overall_max,
            failed_frames=failed_frames,
            mean_threshold=mean_threshold,
            max_threshold=max_threshold,
            per_frame_mean_threshold=per_frame_mean_threshold,
            per_frame_max_threshold=per_frame_max_threshold,
        )
        if failure_messages:
            echo_fn("QC thresholds exceeded:")
            for message in failure_messages:
                echo_fn(f"- {message}")

        if normalized_formats and write_reports:
            report_payload = _build_report_payload(
                first,
                second,
                output,
                frame_stats,
                overall_mean,
                overall_max,
                total_pixels,
                failure_messages,
                _build_threshold_summary(
                    mean_threshold,
                    max_threshold,
                    per_frame_mean_threshold,
                    per_frame_max_threshold,
                ),
            )
            _write_reports(report_payload, normalized_formats)

    return _ComparisonOutcome(
        first=first,
        second=second,
        output=output,
        frame_results=frame_stats,
        overall_mean=overall_mean,
        overall_max=overall_max,
        total_pixels=total_pixels,
        failure_messages=failure_messages,
    )


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
    mean_threshold: float | None = typer.Option(
        None,
        help=(
            "Fail the comparison if the overall mean delta exceeds this threshold. "
            "Ignored when not provided."
        ),
    ),
    max_threshold: float | None = typer.Option(
        None,
        help=(
            "Fail the comparison if the overall max delta exceeds this threshold. "
            "Ignored when not provided."
        ),
    ),
    per_frame_mean_threshold: float | None = typer.Option(
        None,
        help=(
            "Fail the comparison if any frame's mean delta exceeds this threshold. "
            "Ignored when not provided."
        ),
    ),
    per_frame_max_threshold: float | None = typer.Option(
        None,
        help=(
            "Fail the comparison if any frame's max delta exceeds this threshold. "
            "Ignored when not provided."
        ),
    ),
) -> None:
    """Render and compare two scenes or directories of frames."""

    try:
        outcome = _run_comparison(
            first=first,
            second=second,
            output=output,
            report_formats=report_format,
            mean_threshold=mean_threshold,
            max_threshold=max_threshold,
            per_frame_mean_threshold=per_frame_mean_threshold,
            per_frame_max_threshold=per_frame_max_threshold,
        )
    except ChopperRenderError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if outcome.failure_messages:
        raise typer.Exit(code=1)


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
    def __init__(
        self,
        name: str,
        stats: _DiffStats,
        diff_path: Path,
        failures: Sequence[str] | None = None,
    ):
        self.name = name
        self.stats = stats
        self.diff_path = diff_path
        self.failures = list(failures or [])

    @property
    def status(self) -> str:
        return "pass" if not self.failures else "fail"


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


def _evaluate_frame_thresholds(
    result: _FrameResult,
    per_frame_mean_threshold: float | None,
    per_frame_max_threshold: float | None,
) -> None:
    if (
        per_frame_mean_threshold is not None
        and result.stats.mean_delta > per_frame_mean_threshold
    ):
        result.failures.append(
            f"Mean delta {result.stats.mean_delta:.2f} exceeds per-frame mean "
            f"threshold {per_frame_mean_threshold}"
        )

    if (
        per_frame_max_threshold is not None
        and result.stats.max_delta > per_frame_max_threshold
    ):
        result.failures.append(
            f"Max delta {result.stats.max_delta:.2f} exceeds per-frame max "
            f"threshold {per_frame_max_threshold}"
        )


def _collect_failures(
    *,
    overall_mean: float,
    overall_max: float,
    failed_frames: Iterable[_FrameResult],
    mean_threshold: float | None,
    max_threshold: float | None,
    per_frame_mean_threshold: float | None,
    per_frame_max_threshold: float | None,
) -> list[str]:
    failures: list[str] = []

    if mean_threshold is not None and overall_mean > mean_threshold:
        failures.append(
            f"Overall mean delta {overall_mean:.2f} exceeds threshold {mean_threshold}"
        )

    if max_threshold is not None and overall_max > max_threshold:
        failures.append(
            f"Overall max delta {overall_max:.2f} exceeds threshold {max_threshold}"
        )

    failed_frame_list = list(failed_frames)
    if failed_frame_list:
        failures.append(
            f"{len(failed_frame_list)} frame(s) exceeded per-frame thresholds"
        )

    return failures


def _build_threshold_summary(
    mean_threshold: float | None,
    max_threshold: float | None,
    per_frame_mean_threshold: float | None,
    per_frame_max_threshold: float | None,
) -> dict[str, float | None]:
    return {
        "overall_mean_delta": mean_threshold,
        "overall_max_delta": max_threshold,
        "per_frame_mean_delta": per_frame_mean_threshold,
        "per_frame_max_delta": per_frame_max_threshold,
    }


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
    failure_messages: Sequence[str],
    thresholds: Mapping[str, float | None],
) -> dict[str, Any]:
    frames = [
        {
            "frame": result.name,
            "mean_delta": result.stats.mean_delta,
            "max_delta": result.stats.max_delta,
            "pixel_count": result.stats.pixel_count,
            "total_delta": result.stats.total_delta,
            "diff_image": str(output.joinpath(result.diff_path.name)),
            "status": result.status,
            "failures": result.failures,
        }
        for result in frame_results
    ]

    status = "pass" if not failure_messages else "fail"
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
            "thresholds": thresholds,
            "failures": list(failure_messages),
            "failed_frame_count": sum(
                1 for frame in frames if frame.get("status") == "fail"
            ),
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
        "status",
        "failures",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for frame in payload["frames"]:
            writer.writerow(
                {
                    **frame,
                    "failures": "; ".join(frame.get("failures", [])),
                }
            )


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
            f"<td>{frame.get('status', 'pass')}</td>"
            f"<td>{'; '.join(frame.get('failures', []))}</td>"
            "</tr>"
        )
        for frame in payload["frames"]
    )

    metadata = payload["metadata"]
    summary = payload["summary"]
    threshold_items = "\n".join(
        f"<li>{key.replace('_', ' ').title()}: {value}</li>"
        for key, value in summary.get("thresholds", {}).items()
    )
    failure_items = "\n".join(
        f"<li>{failure}</li>" for failure in summary.get("failures", [])
    )
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
    <li>Failed frames: {summary.get('failed_frame_count', 0)}</li>
  </ul>
  <h3>Thresholds</h3>
  <ul>
    {threshold_items}
  </ul>
  <h3>Failures</h3>
  <ul>
    {failure_items or '<li>None</li>'}
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
        <th>Status</th>
        <th>Failures</th>
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


def _hash_scene_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_qc_report(
    output: Path,
    payload: Mapping[str, Any],
    scene_hash: str,
    *,
    scene_path: Path | None,
    export_format: str,
    fps: int,
    samples: int,
    filter_name: str,
    workers: int | None,
    worker_backend: str,
) -> Path:
    normalized_export = export_format.lower()
    suffix = output.suffix.lower()
    frame_formats = {"ppm", "png", "exr", "dpx"}
    animation_suffixes = {".gif", ".mp4"}
    frame_suffixes = {".ppm", ".png", ".exr", ".dpx"}

    if suffix in animation_suffixes:
        report_dir = output.parent
    elif suffix in frame_suffixes:
        report_dir = output
    elif normalized_export in frame_formats:
        report_dir = output
    else:
        report_dir = output.parent
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "qc_report.json"

    metadata: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scene_hash": scene_hash,
        "scene_payload_path": str(scene_path) if scene_path else None,
        "output": str(output),
        "export_format": export_format,
        "fps": fps,
        "samples": samples,
        "filter": filter_name,
        "workers": workers,
        "worker_backend": worker_backend,
    }

    report_payload = {
        "metadata": metadata,
        "scene": payload,
    }

    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    return report_path


def _load_qc_batch_manifest(path: Path) -> list[Mapping[str, Any]]:
    suffix = path.suffix.lower()
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise typer.BadParameter(f"Unable to read manifest {path}: {exc}") from exc

    payload: Any
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise typer.BadParameter(
                "PyYAML is required to load YAML batch manifests."
            ) from exc
        payload = yaml.safe_load(content)
    elif suffix == ".json":
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise typer.BadParameter(
                f"Batch manifest {path} is not valid JSON: {exc}"
            ) from exc
    elif suffix == ".csv":
        reader = csv.DictReader(content.splitlines())
        payload = list(reader)
    else:
        raise typer.BadParameter(
            "Batch manifest must be JSON, YAML, or CSV (got suffix " f"{suffix})."
        )

    entries: Any
    if isinstance(payload, Mapping) and "tasks" in payload:
        entries = payload["tasks"]
    else:
        entries = payload

    if not isinstance(entries, list):
        raise typer.BadParameter("Batch manifest must contain a list of task entries")

    return entries


def _resolve_manifest_path(value: Any, *, base_dir: Path, label: str) -> Path:
    if isinstance(value, (str, Path)):
        path = Path(value)
        if not path.is_absolute():
            path = base_dir / path
        return path
    raise typer.BadParameter(f"{label} must be a string or path")


def _slugify_name(value: str, *, fallback: str) -> str:
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return candidate or fallback


@app.command(name="qc-batch")
def qc_batch(
    manifest: Path = typer.Argument(
        ..., help="Manifest describing QC render/compare tasks (YAML/JSON/CSV)."
    ),
    output: Path = typer.Option(
        Path("qc_batch"),
        "--output",
        "-o",
        help="Base directory for batch task outputs and the consolidated report.",
    ),
    report_format: list[str] = typer.Option(
        ["json"],
        "--report-format",
        "-r",
        help="Report formats (json, csv, html) for individual compare tasks.",
        case_sensitive=False,
    ),
    mean_threshold: float | None = typer.Option(
        None,
        help="Overall mean delta threshold applied when a task does not override it.",
    ),
    max_threshold: float | None = typer.Option(
        None,
        help="Overall max delta threshold applied when a task does not override it.",
    ),
    per_frame_mean_threshold: float | None = typer.Option(
        None,
        help="Per-frame mean delta threshold applied when a task does not override it.",
    ),
    per_frame_max_threshold: float | None = typer.Option(
        None,
        help="Per-frame max delta threshold applied when a task does not override it.",
    ),
) -> None:
    """Execute a QC manifest of renders and comparisons."""

    entries = _load_qc_batch_manifest(manifest)
    manifest_dir = manifest.parent
    output.mkdir(parents=True, exist_ok=True)
    default_formats = _normalize_report_formats(report_format)

    tasks: list[dict[str, Any]] = []
    failures_detected = False

    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, Mapping):
            raise typer.BadParameter("Each batch task must be a mapping of settings")

        name = str(entry.get("name") or f"task-{index}")
        slug = _slugify_name(name, fallback=f"task-{index}")
        task_output = output / slug
        task_record: dict[str, Any] = {"name": name}

        if "scene" in entry:
            task_record["type"] = "render"
            if entry.get("scene") is not None:
                task_record["scene"] = str(entry.get("scene"))
            render_output = _resolve_manifest_path(
                entry.get("output", task_output / "frames"),
                base_dir=manifest_dir,
                label=f"output for task {name!r}",
            )
            try:
                qc_render(
                    output=render_output,
                    export=str(entry.get("format", "png")),
                    fps=int(entry.get("fps", 24)),
                    samples=int(entry.get("samples", 2)),
                    downsample_filter=str(entry.get("filter", "box")),
                    preset=str(entry.get("preset", "hd-1080")),
                    resolution=entry.get("resolution"),
                    aspect=entry.get("aspect"),
                    slate_text=entry.get("slate_text"),
                    timecode=entry.get("timecode"),
                    studio_logo=bool(entry.get("studio_logo", False)),
                )
                task_record.update(
                    {
                        "status": "pass",
                        "output": str(render_output),
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive
                task_record.update({"status": "error", "error": str(exc)})
                failures_detected = True
        elif "first" in entry and "second" in entry:
            task_record["type"] = "compare"
            compare_output = _resolve_manifest_path(
                entry.get("output", task_output / "diff"),
                base_dir=manifest_dir,
                label=f"output for task {name!r}",
            )
            task_formats_raw = entry.get("report_format", default_formats)
            if isinstance(task_formats_raw, str):
                task_formats_raw = [task_formats_raw]
            task_formats = _normalize_report_formats(task_formats_raw)
            task_mean_threshold = entry.get("mean_threshold", mean_threshold)
            task_max_threshold = entry.get("max_threshold", max_threshold)
            task_per_frame_mean = entry.get(
                "per_frame_mean_threshold", per_frame_mean_threshold
            )
            task_per_frame_max = entry.get(
                "per_frame_max_threshold", per_frame_max_threshold
            )

            try:
                first_path = _resolve_manifest_path(
                    entry["first"],
                    base_dir=manifest_dir,
                    label=f"first source for task {name!r}",
                )
                second_path = _resolve_manifest_path(
                    entry["second"],
                    base_dir=manifest_dir,
                    label=f"second source for task {name!r}",
                )
                outcome = _run_comparison(
                    first=first_path,
                    second=second_path,
                    output=compare_output,
                    report_formats=task_formats,
                    mean_threshold=task_mean_threshold,
                    max_threshold=task_max_threshold,
                    per_frame_mean_threshold=task_per_frame_mean,
                    per_frame_max_threshold=task_per_frame_max,
                )
                task_record.update(
                    {
                        "status": outcome.status,
                        "output": str(compare_output),
                        "first": str(first_path),
                        "second": str(second_path),
                        "overall_mean": outcome.overall_mean,
                        "overall_max": outcome.overall_max,
                        "total_pixels": outcome.total_pixels,
                        "failures": outcome.failure_messages,
                    }
                )
                if outcome.failure_messages:
                    failures_detected = True
            except (ChopperRenderError, typer.BadParameter) as exc:
                task_record.update({"status": "error", "error": str(exc)})
                failures_detected = True
        else:
            raise typer.BadParameter(
                "Each task must include either a 'scene' for qc-render or both "
                "'first' and 'second' for comparisons."
            )

        tasks.append(task_record)

    report_payload = {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "manifest": str(manifest),
            "output": str(output),
        },
        "summary": {
            "total": len(tasks),
            "passed": sum(1 for task in tasks if task.get("status") == "pass"),
            "failed": sum(1 for task in tasks if task.get("status") == "fail"),
            "errors": sum(1 for task in tasks if task.get("status") == "error"),
        },
        "tasks": tasks,
    }

    report_path = output / "qc_batch_report.json"
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    typer.echo(f"Batch report written to {report_path}")

    if failures_detected:
        raise typer.Exit(code=1)


__all__ = [
    "app",
    "inspect",
    "render",
    "qc_batch",
    "compare",
    "_load_scene",
]
