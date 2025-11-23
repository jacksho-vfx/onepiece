"""Typer command-line interface for the Chopper renderer."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

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

    return GuidesOverlay(
        safe_frame=safe_frame,
        action_frame=action_frame,
        thirds_grid=thirds_grid,
        center_mark=center_mark,
        color=overlay_color,
        opacity=guides_opacity,
        stroke_width=guides_width,
    )


def _build_qc_scene_payload(width: int = 1920, height: int = 1080) -> dict[str, Any]:
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
            " or 'gif'/'mp4' for bundled animations."
        ),
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
) -> None:
    """Render a scene description and write the frames to disk."""

    export_was_explicit = _was_option_explicit("export")
    background_override: Color | None = None
    frame_list: list[int] | None = None
    color_space_choice: ColorSpace | None = None
    guides_overlay: GuidesOverlay | None = None

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

    if color_space is not None:
        try:
            color_space_choice = ColorSpace.from_value(color_space)
        except SceneError as exc:
            raise typer.BadParameter(str(exc)) from exc

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
            start_frame=start,
            end_frame=end,
            frames=frame_list,
            samples=samples,
            filter_name=downsample_filter,
            workers=workers,
            worker_backend=worker_backend,
            guides=guides_overlay,
            color_space=color_space_choice,
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
    if color_space is not None:
        try:
            color_space_choice = ColorSpace.from_value(color_space)
        except SceneError as exc:
            raise typer.BadParameter(str(exc)) from exc

    qc_scene_payload = _build_qc_scene_payload()

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

        total_delta = 0.0
        total_pixels = 0
        overall_max = 0.0

        for left, right in zip(first_list, second_list):
            if left.name != right.name:
                raise typer.BadParameter("Frame names must match between directories")

            diff_stats = _write_diff(left, right, output)
            frame_pixels = diff_stats.pixel_count
            total_delta += diff_stats.total_delta
            total_pixels += frame_pixels
            overall_max = max(overall_max, diff_stats.max_delta)

            typer.echo(
                f"{left.name}: mean delta {diff_stats.mean_delta:.2f}, "
                f"max delta {diff_stats.max_delta:.2f}"
            )

        overall_mean = total_delta / total_pixels if total_pixels else 0.0
        typer.echo(
            f"Overall: mean delta {overall_mean:.2f}, max delta {overall_max:.2f}"
        )


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


def _write_diff(left: Path, right: Path, output_dir: Path) -> _DiffStats:
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
    return _DiffStats(mean_delta, max_delta, pixel_count)


__all__ = [
    "app",
    "inspect",
    "render",
    "compare",
    "_load_scene",
]
