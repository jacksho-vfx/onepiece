"""Helpers for validating and parsing ingest media filenames."""

from __future__ import annotations

from libraries.platform.validations.naming import (
    validate_episode_name,
    validate_scene_name,
    validate_shot,
    validate_shot_name,
    validate_show_name,
)

from .exceptions import FilenameValidationError
from .models import MediaInfo


def parse_media_filename(filename: str) -> MediaInfo:
    """Parse *filename* using the production naming conventions."""

    stem, dot, extension = filename.partition(".")
    if not dot:
        raise FilenameValidationError("File is missing an extension")

    parts = stem.split("_")
    if len(parts) < 5:
        raise FilenameValidationError(
            "Filename must contain show, episode, scene, shot, and descriptor"
        )

    show_code, episode, scene, shot, *descriptor_parts = parts

    if not validate_show_name(show_code):
        raise FilenameValidationError(f"Invalid show code: {show_code}")
    if not validate_episode_name(episode):
        raise FilenameValidationError(f"Invalid episode: {episode}")
    if not validate_scene_name(scene):
        raise FilenameValidationError(f"Invalid scene: {scene}")
    if not validate_shot(shot):
        raise FilenameValidationError(f"Invalid shot: {shot}")

    shot_name = f"{episode}_{scene}_{shot}"
    if not validate_shot_name(shot_name):
        raise FilenameValidationError(f"Invalid shot name: {shot_name}")

    descriptor = "_".join(descriptor_parts)
    if not descriptor:
        raise FilenameValidationError("Descriptor must be provided in the filename")

    return MediaInfo(
        show_code=show_code,
        episode=episode,
        scene=scene,
        shot=shot,
        descriptor=descriptor,
        extension=extension,
    )


__all__ = ["parse_media_filename"]
