"""Typer command-line interface for the Chopper renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .renderer import AnimationWriter, Renderer, Scene, SceneError

app = typer.Typer(help="Render self-contained scene descriptions using Chopper.")


def _load_scene(path: Path) -> Scene:
    """Load a :class:`Scene` from the supplied JSON file."""

    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise typer.BadParameter(f"Scene file '{path}' was not found") from exc

    try:
        payload: dict[str, Any] = json.loads(contents)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise typer.BadParameter(f"Scene file '{path}' is not valid JSON") from exc

    try:
        return Scene.from_dict(payload)
    except SceneError as exc:
        raise typer.BadParameter(f"Scene file '{path}' is invalid: {exc}") from exc


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
) -> None:
    """Render a scene description and write the frames to disk."""

    parsed_scene = _load_scene(scene)
    renderer = Renderer(parsed_scene)
    frames = renderer.render()

    export_normalized = export.lower()

    if export_normalized not in {"ppm", "png", "gif", "mp4"}:
        raise typer.BadParameter("format must be one of: ppm, png, gif, mp4")

    if export_normalized in {"ppm", "png"}:
        output.mkdir(parents=True, exist_ok=True)
        for frame in frames:
            frame_path = output / f"frame_{frame.index:04d}.{export_normalized}"
            if export_normalized == "ppm":
                frame.save_ppm(frame_path)
            else:
                frame.save_png(frame_path)
        typer.echo(f"Rendered {len(frames)} frame(s) to {output}")
        return

    destination = output
    suffix = f".{export_normalized}"
    if destination.suffix.lower() != suffix:
        destination = destination.with_suffix(suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)

    writer = AnimationWriter(frames=frames, fps=fps)
    if export_normalized == "gif":
        writer.write_gif(destination)
    else:
        writer.write_mp4(destination)

    typer.echo(f"Rendered {len(frames)} frame(s) to {destination}")


__all__ = ["app", "render"]
