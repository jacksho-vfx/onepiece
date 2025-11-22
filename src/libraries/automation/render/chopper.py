"""Helpers for the Chopper command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from apps.chopper.renderer import (
    AnimationWriter,
    Color,
    Renderer,
    Scene,
    SceneError,
)

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
    except (UnicodeDecodeError, ValueError) as exc:
        raise ChopperRenderError(
            f"Scene file '{path}' could not be decoded as UTF-8"
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


def _write_animation(
    frames: Iterable[Any], destination: Path, export_format: str, fps: int
) -> int:
    """Encode ``frames`` as an animation at ``destination``."""

    if fps <= 0:
        raise ChopperRenderError(
            "Frames per second must be greater than zero when encoding animations."
        )

    writer = AnimationWriter(frames=frames, fps=fps)
    try:
        if export_format == "gif":
            frame_count = int(writer.write_gif(destination))
        else:
            frame_count = int(writer.write_mp4(destination))
    except (RuntimeError, ValueError) as exc:
        raise ChopperRenderError(str(exc)) from exc

    return frame_count


def _render_message(
    frame_count: int, destination: Path, description: str | None
) -> str:
    suffix = f" to {destination}"
    if description:
        return f"Rendered {frame_count} frame(s) {description}{suffix}"
    return f"Rendered {frame_count} frame(s){suffix}"


def _resolve_frame_indices(
    *,
    frame_count: int,
    start_frame: int | None,
    end_frame: int | None,
    frames: Iterable[int] | None,
) -> list[int] | None:
    """Validate frame selection parameters and return a list of indices."""

    upper = frame_count - 1

    if frames is not None:
        if start_frame is not None or end_frame is not None:
            raise ChopperRenderError(
                "Cannot combine --frames with --start/--end options"
            )
        provided_indices = list(frames)
        if not provided_indices:
            raise ChopperRenderError("At least one frame index must be provided")
        indices = sorted(set(provided_indices))
    elif start_frame is None and end_frame is None:
        return None
    else:
        start = start_frame if start_frame is not None else 0
        end = end_frame if end_frame is not None else frame_count - 1
        if start < 0 or end < 0:
            raise ChopperRenderError("Frame indices must be zero or greater")
        if start > upper or end > upper:
            raise ChopperRenderError(
                f"Frame indices must be within the 0-{upper} range"
            )
        if start > end:
            raise ChopperRenderError("Start frame cannot be greater than end frame")
        indices = list(range(start, end + 1))

    for index in indices:
        if index < 0 or index > upper:
            raise ChopperRenderError(
                f"Frame index {index} is outside the valid range 0-{upper}"
            )

    # Remove duplicates while preserving order to avoid rendering the same frame twice
    seen: set[int] = set()
    deduped: list[int] = []
    for index in indices:
        if index not in seen:
            seen.add(index)
            deduped.append(index)

    return deduped


def _frame_selection_description(frame_indices: list[int] | None) -> str | None:
    if not frame_indices:
        return None

    if len(frame_indices) == 1:
        return f"(frame {frame_indices[0]})"

    if _is_contiguous(frame_indices):
        ordered = sorted(frame_indices)
        return f"(frames {ordered[0]}-{ordered[-1]})"

    joined = ", ".join(str(value) for value in frame_indices)
    return f"(frames {joined})"


def _is_contiguous(values: list[int]) -> bool:
    if len(values) < 2:
        return True
    sorted_values = sorted(values)
    return sorted_values == list(range(sorted_values[0], sorted_values[-1] + 1))


def render_scene(
    scene_path: Path,
    output_path: Path,
    export_format: str,
    fps: int,
    *,
    export_was_explicit: bool = False,
    background_override: Color | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
    frames: Iterable[int] | None = None,
    samples: int = 1,
    filter_name: str = "box",
) -> str:
    """Render ``scene_path`` to ``output_path`` and return a status message."""

    parsed_scene = load_scene(scene_path)
    if background_override is not None:
        parsed_scene.background = background_override
    if samples <= 0:
        raise ChopperRenderError("Supersampling 'samples' must be greater than zero")
    try:
        renderer = Renderer(parsed_scene, samples=samples, filter_name=filter_name)
    except SceneError as exc:
        raise ChopperRenderError(str(exc)) from exc

    frame_indices = _resolve_frame_indices(
        frame_count=parsed_scene.frame_count,
        start_frame=start_frame,
        end_frame=end_frame,
        frames=frames,
    )
    frames_iter = renderer.render(frames=frame_indices)

    export_normalized = _normalize_export_format(
        output_path=output_path,
        export_format=export_format,
        export_was_explicit=export_was_explicit,
    )

    frame_description = _frame_selection_description(frame_indices)

    if export_normalized in {"ppm", "png"}:
        output_path.mkdir(parents=True, exist_ok=True)
        frame_count = _write_frames(frames_iter, output_path, export_normalized)
        return _render_message(frame_count, output_path, frame_description)

    destination = output_path
    suffix = f".{export_normalized}"
    if destination.suffix.lower() != suffix:
        destination = destination.with_suffix(suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)

    frame_count = _write_animation(frames_iter, destination, export_normalized, fps)

    return _render_message(frame_count, destination, frame_description)
