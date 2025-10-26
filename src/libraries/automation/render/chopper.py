"""Helpers for the Chopper command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from apps.chopper.renderer import AnimationWriter, Renderer, Scene, SceneError

__all__ = ["ChopperRenderError", "load_scene", "render_scene"]


class ChopperRenderError(ValueError):
    """Raised when rendering a Chopper scene fails."""


def load_scene(path: Path) -> Scene:
    """Load a :class:`Scene` from ``path`` and return the parsed model."""

    try:
        contents = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise ChopperRenderError(f"Scene file '{path}' was not found") from exc
    except IsADirectoryError as exc:
        raise ChopperRenderError(
            f"Scene path '{path}' is a directory; expected a JSON file"
        ) from exc
    except PermissionError as exc:
        raise ChopperRenderError(
            f"Scene file '{path}' cannot be read due to permissions"
        ) from exc
    except OSError as exc:
        raise ChopperRenderError(
            f"Scene file '{path}' could not be read: {exc}"
        ) from exc

    try:
        payload: dict[str, Any] = json.loads(contents)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ChopperRenderError(f"Scene file '{path}' is not valid JSON") from exc

    try:
        return Scene.from_dict(payload)
    except SceneError as exc:
        raise ChopperRenderError(f"Scene file '{path}' is invalid: {exc}") from exc


def _normalize_export_format(
    output_path: Path,
    export_format: str,
    export_was_explicit: bool,
) -> str:
    """Return the export format inferred from ``output_path`` and ``export_format``."""

    suffix_map = {
        ".ppm": "ppm",
        ".png": "png",
        ".gif": "gif",
        ".mp4": "mp4",
    }

    export_normalized = export_format.lower()
    inferred_format = suffix_map.get(output_path.suffix.lower())

    if inferred_format is not None:
        if not export_was_explicit:
            export_normalized = inferred_format
        elif inferred_format != export_normalized:
            suffix_display = output_path.suffix or ""
            raise ChopperRenderError(
                f"Output path suffix '{suffix_display}' conflicts with --format '{export_format}'."
            )

    if export_normalized not in {"ppm", "png", "gif", "mp4"}:
        raise ChopperRenderError("format must be one of: ppm, png, gif, mp4")

    return export_normalized


def _write_frames(
    frames: Iterable[Any],
    output_path: Path,
    export_format: str,
) -> int:
    """Persist ``frames`` as image files and return the number written."""

    frame_count = 0
    for frame in frames:
        frame_path = output_path / f"frame_{frame.index:04d}.{export_format}"
        if export_format == "ppm":
            frame.save_ppm(frame_path)
        else:
            try:
                frame.save_png(frame_path)
            except RuntimeError as exc:
                raise ChopperRenderError(str(exc)) from exc
        frame_count += 1
    return frame_count


def _write_animation(frames: list[Any], destination: Path, export_format: str, fps: int) -> int:
    """Encode ``frames`` as an animation at ``destination``."""

    if fps <= 0:
        raise ChopperRenderError(
            "Frames per second must be greater than zero when encoding animations."
        )

    writer = AnimationWriter(frames=frames, fps=fps)
    try:
        if export_format == "gif":
            writer.write_gif(destination)
        else:
            writer.write_mp4(destination)
    except RuntimeError as exc:
        raise ChopperRenderError(str(exc)) from exc

    return len(frames)


def render_scene(
    scene_path: Path,
    output_path: Path,
    export_format: str,
    fps: int,
    *,
    export_was_explicit: bool = False,
) -> str:
    """Render ``scene_path`` to ``output_path`` and return a status message."""

    parsed_scene = load_scene(scene_path)
    renderer = Renderer(parsed_scene)
    frames_iter = renderer.render()

    export_normalized = _normalize_export_format(
        output_path=output_path,
        export_format=export_format,
        export_was_explicit=export_was_explicit,
    )

    if export_normalized in {"ppm", "png"}:
        output_path.mkdir(parents=True, exist_ok=True)
        frame_count = _write_frames(frames_iter, output_path, export_normalized)
        return f"Rendered {frame_count} frame(s) to {output_path}"

    destination = output_path
    suffix = f".{export_normalized}"
    if destination.suffix.lower() != suffix:
        destination = destination.with_suffix(suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)

    frames = list(frames_iter)
    frame_count = _write_animation(frames, destination, export_normalized, fps)

    return f"Rendered {frame_count} frame(s) to {destination}"
