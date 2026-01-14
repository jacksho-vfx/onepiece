"""Base handler types for optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from libraries.pipeline.optimize.report import OptimizationStep


@dataclass
class HandlerResult:
    steps: list[OptimizationStep] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    output_files: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class HandlerContext:
    project_root: Path
    asset_id: str
    payload_root: Path
    output_root: Path
    variant: str
    settings: dict[str, Any]
    tags: set[str]
    metadata_path: Path
