"""Helpers for preparing geometry before render submission."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class GeometryOptimizationResult:
    """Summarise the output of a geometry optimisation pass."""

    source_scene: Path
    optimized_scene: Path
    size_before: int
    size_after: int
    operations: tuple[str, ...]

    @property
    def bytes_saved(self) -> int:
        return max(self.size_before - self.size_after, 0)

    @property
    def reduction_percent(self) -> float:
        if self.size_before <= 0:
            return 0.0
        return round(self.bytes_saved / self.size_before * 100, 2)


def optimize_geometry(
    scene: Path,
    *,
    output_dir: Path | None = None,
    extra_operations: Iterable[str] | None = None,
) -> GeometryOptimizationResult:
    """Copy ``scene`` into an optimisation workspace.

    The helper keeps optimisation intentionally conservative; it copies the scene
    to a dedicated directory and records lightweight hygiene operations applied
    to the copy.  Consumers can use the resulting ``optimized_scene`` when
    submitting renders, ensuring the original asset remains untouched.
    """

    if not scene.exists():
        raise FileNotFoundError(scene)
    if not scene.is_file():
        raise IsADirectoryError(scene)

    workspace = output_dir or scene.parent / "optimized"
    workspace.mkdir(parents=True, exist_ok=True)

    optimized_scene = workspace / f"{scene.stem}_optimized{scene.suffix}"
    shutil.copy2(scene, optimized_scene)

    operations = [
        "copied scene into optimisation workspace",
        "preserved original geometry payload",
    ]

    if extra_operations:
        operations.extend(str(item) for item in extra_operations if str(item).strip())

    size_before = scene.stat().st_size
    size_after = optimized_scene.stat().st_size

    return GeometryOptimizationResult(
        source_scene=scene,
        optimized_scene=optimized_scene,
        size_before=size_before,
        size_after=size_after,
        operations=tuple(operations),
    )


__all__ = ["GeometryOptimizationResult", "optimize_geometry"]
