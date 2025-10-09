"""Typer command-line interface for the Chopper renderer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .renderer import Renderer, Scene

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

    return Scene.from_dict(payload)


@app.command()
def render(
    scene: Path = typer.Argument(..., help="Path to the JSON scene description."),
    output: Path = typer.Option(
        Path("frames"),
        "--output",
        "-o",
        help="Directory where rendered frames will be written as PPM files.",
    ),
) -> None:
    """Render a scene description and write the frames to disk."""

    parsed_scene = _load_scene(scene)
    renderer = Renderer(parsed_scene)
    frames = renderer.render()

    output.mkdir(parents=True, exist_ok=True)

    for frame in frames:
        frame_path = output / f"frame_{frame.index:04d}.ppm"
        frame.save_ppm(frame_path)

    typer.echo(f"Rendered {len(frames)} frame(s) to {output}")


__all__ = ["app", "render"]
