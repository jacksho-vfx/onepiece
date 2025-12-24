"""Helpers for discovering and running bundled Unreal scripts."""

from __future__ import annotations

import ast
import runpy
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class UnrealScript:
    """Describe a runnable Unreal Python script."""

    label: str
    path: Path
    description: str | None = None

    def run(self) -> None:
        normalized = self.path.expanduser().resolve()
        log.info("unreal.scripts.run", label=self.label, path=str(normalized))
        runpy.run_path(str(normalized), run_name="__main__")


def _label_from_path(path: Path) -> str:
    return path.stem.replace("_", " ").title()


def _extract_description(path: Path) -> str | None:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, SyntaxError, OSError):
        return None

    description = ast.get_docstring(module)
    if not description:
        return None
    return description.strip().splitlines()[0]


def discover_unreal_scripts(directory: Path) -> list[UnrealScript]:
    """Return runnable definitions for each Python file in *directory*."""

    if not directory.exists() or not directory.is_dir():
        return []

    scripts: list[UnrealScript] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("__"):
            continue
        scripts.append(
            UnrealScript(
                label=_label_from_path(path),
                path=path,
                description=_extract_description(path),
            )
        )
    return scripts


def script_actions_from_definitions(
    definitions: Iterable[UnrealScript],
) -> list[dict[str, str | Path | None]]:
    """Return metadata dictionaries describing script menu entries."""

    return [
        {
            "label": f"Run {definition.label}",
            "description": definition.description,
            "path": definition.path,
        }
        for definition in definitions
    ]


__all__ = [
    "UnrealScript",
    "discover_unreal_scripts",
    "script_actions_from_definitions",
]
