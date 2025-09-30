"""Helpers for writing dailies manifest files."""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, TypeVar

__all__ = ["write_manifest"]

TDataclass = TypeVar("TDataclass")


def _clip_to_mapping(clip: Any) -> Any:
    if is_dataclass(clip):
        return asdict(clip)  # type: ignore[call-overload]
    if isinstance(clip, Mapping):
        return clip
    return {
        "shot": getattr(clip, "shot", ""),
        "version": getattr(clip, "version", ""),
        "source_path": getattr(clip, "source_path", ""),
        "frame_range": getattr(clip, "frame_range", ""),
        "user": getattr(clip, "user", ""),
        "duration_seconds": getattr(clip, "duration_seconds", None),
    }


def write_manifest(
    output: Path,
    clips: Iterable[Any],
    *,
    codec: str,
) -> Path:
    """Write a manifest JSON file describing the rendered dailies clips."""

    manifest_path = output.with_name(f"{output.name}.manifest.json")
    payload = {
        "output": str(output),
        "codec": codec,
        "generated_at": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
        "clips": [dict(_clip_to_mapping(clip)) for clip in clips],
    }
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest_path
