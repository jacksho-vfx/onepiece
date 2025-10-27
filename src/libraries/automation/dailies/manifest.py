"""Helpers for writing dailies manifest files."""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence, TypeGuard, cast

__all__ = ["write_manifest"]


class DataclassInstance(Protocol):
    __dataclass_fields__: dict[str, Any]


def _is_dataclass_instance(obj: Any) -> TypeGuard[DataclassInstance]:
    """Narrow Any to DataclassInstance for mypy."""
    return is_dataclass(obj) and not isinstance(obj, type)


def _clip_to_mapping(clip: Any) -> Mapping[str, Any]:
    if _is_dataclass_instance(clip):
        return asdict(cast(Any, clip))
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


def _normalise_value(value: Any) -> Any:
    """Convert *value* into a JSON serialisable representation."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (Decimal,)):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if _is_dataclass_instance(value):
        return _normalise_mapping(asdict(cast(Any, value)))
    if isinstance(value, Mapping):
        return _normalise_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return [_normalise_value(item) for item in value]
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - defensive
            return value.hex()
    return str(value)


def _normalise_mapping(mapping: Mapping[Any, Any]) -> dict[str, Any]:
    return {
        str(key): _normalise_value(value)
        for key, value in mapping.items()
        if value is not None
    }


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return None


def _build_summary(clips: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"clip_count": len(clips)}
    durations = [
        duration
        for duration in (_coerce_float(clip.get("duration_seconds")) for clip in clips)
        if duration is not None
    ]
    if durations:
        total = sum(durations)
        summary["total_duration_seconds"] = total
        summary["average_duration_seconds"] = total / len(durations)
    shots = sorted(
        {str(clip.get("shot")) for clip in clips if clip.get("shot") not in (None, "")}
    )
    if shots:
        summary["shots"] = shots
    return summary


def write_manifest(
    output: Path,
    clips: Iterable[Any],
    *,
    codec: str,
    metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write a manifest JSON file describing the rendered dailies clips.

    The manifest captures a summary of the provided *clips* and optionally
    embeds additional *metadata* about the render session.
    """

    manifest_path = output.with_name(f"{output.name}.manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    raw_clips = [dict(_clip_to_mapping(clip)) for clip in clips]
    payload = {
        "output": str(output),
        "codec": codec,
        "generated_at": _dt.datetime.now(tz=_dt.timezone.utc).isoformat(),
        "clips": [_normalise_mapping(clip) for clip in raw_clips],
        "summary": _build_summary(raw_clips),
    }
    if metadata:
        payload["metadata"] = _normalise_mapping(metadata)
    manifest_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest_path
