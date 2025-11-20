"""Typer command-line interface for the Chopper renderer."""

from __future__ import annotations

from pathlib import Path

import click
from click.core import ParameterSource
import typer

from apps.chopper.renderer import Color, Scene, SceneError, parse_color
from libraries.automation.render.chopper import (
    ChopperRenderError,
    load_scene,
    render_scene,
)


app = typer.Typer(help="Render self-contained scene descriptions using Chopper.")


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
    background: str | None = typer.Option(
        None,
        "--background",
        "-b",
        help="Override the scene background colour using a hex value like '#112233'.",
    ),
) -> None:
    """Render a scene description and write the frames to disk."""

    export_was_explicit = False
    background_override: Color | None = None

    try:
        ctx = click.get_current_context(silent=True)
    except RuntimeError:  # pragma: no cover - defensive
        ctx = None

    if ctx is not None:
        try:
            parameter_source = ctx.get_parameter_source("export")
        except (AttributeError, KeyError):  # pragma: no cover - defensive
            parameter_source = None
        export_was_explicit = parameter_source not in (None, ParameterSource.DEFAULT)

    if background is not None:
        try:
            background_override = parse_color(background)
        except SceneError as exc:
            raise typer.BadParameter(str(exc)) from exc

    try:
        message = render_scene(
            scene_path=scene,
            output_path=output,
            export_format=export,
            fps=fps,
            export_was_explicit=export_was_explicit,
            background_override=background_override,
        )
    except ChopperRenderError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(message)


__all__ = ["app", "inspect", "render", "_load_scene"]
