"""Optimization report structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OptimizationStep:
    name: str
    status: str
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name, "status": self.status}
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass
class OptimizationReport:
    schema_version: str
    asset_id: str
    variant: str
    input_path: str
    input_hash: str
    input_size_bytes: int
    output_path: str
    output_size_bytes: int
    settings: dict[str, Any]
    tool_versions: dict[str, str]
    metrics: dict[str, Any]
    steps: list[OptimizationStep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "variant": self.variant,
            "input": {
                "path": self.input_path,
                "hash": self.input_hash,
                "size_bytes": self.input_size_bytes,
            },
            "output": {
                "path": self.output_path,
                "size_bytes": self.output_size_bytes,
            },
            "settings": self.settings,
            "tool_versions": self.tool_versions,
            "metrics": self.metrics,
            "steps": [step.to_dict() for step in self.steps],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }
