"""Cache optimization handler."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from libraries.pipeline.ingest.detection import ASSET_TYPE_CACHE, normalize_extension
from libraries.pipeline.optimize.handlers.base import HandlerContext, HandlerResult
from libraries.pipeline.optimize.report import OptimizationStep

SUPPORTED_EXTENSIONS = {".abc", ".vdb", ".bgeo", ".bgeo.sc", ".usd", ".usda", ".usdc"}


@dataclass(frozen=True)
class CacheMetrics:
    frame_start: int | None = None
    frame_end: int | None = None
    missing_frames: list[int] | None = None
    file_count: int = 0


def _find_cache_files(payload_root: Path) -> list[Path]:
    if payload_root.is_file():
        return (
            [payload_root]
            if normalize_extension(payload_root) in SUPPORTED_EXTENSIONS
            else []
        )
    return sorted(
        [
            path
            for path in payload_root.rglob("*")
            if normalize_extension(path) in SUPPORTED_EXTENSIONS
        ]
    )


def _extract_frame_number(name: str) -> int | None:
    match = re.search(r"(\\d+)(?!.*\\d)", name)
    if not match:
        return None
    return int(match.group(1))


def _validate_frames(files: Iterable[Path]) -> CacheMetrics:
    frames: list[int] = []
    for path in files:
        frame = _extract_frame_number(path.stem)
        if frame is not None:
            frames.append(frame)
    if not frames:
        return CacheMetrics(file_count=len(list(files)))
    frames_sorted = sorted(frames)
    expected = set(range(frames_sorted[0], frames_sorted[-1] + 1))
    missing = sorted(expected - set(frames_sorted))
    return CacheMetrics(
        frame_start=frames_sorted[0],
        frame_end=frames_sorted[-1],
        missing_frames=missing,
        file_count=len(frames),
    )


def optimize_caches(context: HandlerContext) -> HandlerResult:
    result = HandlerResult()
    cache_files = _find_cache_files(context.payload_root)
    if not cache_files:
        result.steps.append(
            OptimizationStep(
                name="detect_caches",
                status="skipped",
                detail="No cache files detected.",
            )
        )
        return result

    output_root = context.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    settings = context.settings
    if settings.get("proxy"):
        result.steps.append(
            OptimizationStep(
                name="generate_proxy",
                status="skipped",
                detail="Proxy generation requires external tools.",
            )
        )
        result.warnings.append("Cache proxy generation skipped: tool unavailable.")

    if settings.get("validate_frames", True):
        metrics = _validate_frames(cache_files)
        result.metrics.update(
            {
                "frame_start": metrics.frame_start,
                "frame_end": metrics.frame_end,
                "missing_frames": metrics.missing_frames,
                "file_count": metrics.file_count,
            }
        )
        result.steps.append(OptimizationStep(name="validate_frames", status="ok"))

    for cache in cache_files:
        relative = (
            cache.relative_to(context.payload_root)
            if context.payload_root.is_dir()
            else Path(cache.name)
        )
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache, destination)
        result.output_files.append(destination)
    result.steps.append(OptimizationStep(name="copy_cache", status="ok"))
    return result


def supports(types: Iterable[str]) -> bool:
    return ASSET_TYPE_CACHE in set(types)
