"""Helpers for working with Cinema 4D metadata exports."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, cast

from libraries.creative.dcc.utils import normalize_frame_range

__all__ = ["SUMMARY_ENV_VAR", "load_cinema4d_summary"]

SUMMARY_ENV_VAR = "ONEPIECE_CINEMA4D_SUMMARY"


def _clean_name(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    cleaned = value.strip()
    return cleaned or None


def _normalize_summary_frame_range(value: Any) -> tuple[int, int] | None:
    if value is None:
        return None

    if isinstance(value, Mapping):
        start = value.get("start")
        end = value.get("end")
        value = (start, end)

    if isinstance(value, (list, tuple)) and len(value) == 2:
        start, end = value
        if start is None or end is None:
            return None
        return cast(tuple[int, int], normalize_frame_range((start, end)))

    raise ValueError("frame_range must contain two values")


def load_cinema4d_summary(
    *, env: Mapping[str, str] | None = None
) -> dict[str, Any] | None:
    """Return the Cinema 4D summary payload sourced from the environment."""

    env_mapping: Mapping[str, str] = env if env is not None else os.environ
    summary_path = env_mapping.get(SUMMARY_ENV_VAR)
    if not summary_path:
        return None

    path = Path(summary_path).expanduser()
    try:
        raw_text = path.read_text()
    except OSError:
        return None

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    summary: dict[str, Any] = dict(payload)

    raw_frame_range = payload.get("frame_range")
    try:
        frame_range = _normalize_summary_frame_range(raw_frame_range)
    except (TypeError, ValueError):
        frame_range = None
    if "frame_range" in payload or frame_range is not None:
        summary["frame_range"] = list(frame_range) if frame_range is not None else None

    renderer = payload.get("renderer")
    if renderer is None:
        render_settings = payload.get("render_settings")
        if isinstance(render_settings, Mapping):
            renderer = render_settings.get("renderer")
    renderer = _clean_name(renderer)
    if "renderer" in payload or renderer is not None:
        summary["renderer"] = renderer

    take = payload.get("take")
    if take is None:
        takes = payload.get("takes")
        if isinstance(takes, Mapping):
            take = takes.get("active")
    take = _clean_name(take)
    if "take" in payload or take is not None:
        summary["take"] = take

    return summary
