"""Helpers for discovering and deploying Cinema 4D utility scripts."""

from __future__ import annotations

import ast
import runpy
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

import structlog

log = structlog.get_logger(__name__)


DEFAULT_SCRIPT_DIRECTORY = Path(__file__).parent / "scripts"


@dataclass(frozen=True, slots=True)
class Cinema4DScript:
    """Describe a runnable Cinema 4D Python script."""

    path: Path
    label: str
    description: str | None = None

    def run(self) -> None:
        """Execute the script with a clean ``__main__`` namespace."""

        normalized = self.path.expanduser().resolve()
        log.info("cinema4d.script.run", script=str(normalized))
        runpy.run_path(str(normalized), run_name="__main__")

    @classmethod
    def from_path(cls, path: Path) -> "Cinema4DScript":
        """Create a :class:`Cinema4DScript` from a Python file."""

        normalized = path.expanduser().resolve()
        description = _read_module_docstring(normalized)
        label = _label_from_filename(normalized.name)
        return cls(path=normalized, label=label, description=description)


def _label_from_filename(filename: str) -> str:
    stem = filename.rsplit(".", maxsplit=1)[0]
    return stem.replace("_", " ").title()


def _read_module_docstring(path: Path) -> str | None:
    try:
        parsed = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        log.debug(
            "cinema4d.script.docstring_unavailable", script=str(path), error=str(exc)
        )
        return None
    return ast.get_docstring(parsed)


def default_script_directory() -> Path:
    """Return the repository-managed Cinema 4D script directory."""

    return DEFAULT_SCRIPT_DIRECTORY


def discover_cinema4d_scripts(directory: Path | None = None) -> list[Cinema4DScript]:
    """Return definitions for all Python scripts in ``directory``."""

    script_dir = directory or default_script_directory()
    if not script_dir.exists() or not script_dir.is_dir():
        log.debug("cinema4d.script_directory_missing", directory=str(script_dir))
        return []

    scripts: list[Cinema4DScript] = []
    for path in sorted(script_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        scripts.append(Cinema4DScript.from_path(path))
    return scripts


def deploy_scripts_to_directory(
    destination: Path, scripts: Sequence[Cinema4DScript] | None = None
) -> list[Path]:
    """Copy the provided scripts into ``destination``.

    Returns the list of copied file paths.
    """

    destination.mkdir(parents=True, exist_ok=True)
    resolved_scripts = list(scripts or discover_cinema4d_scripts())
    copied: list[Path] = []

    for script in resolved_scripts:
        target = destination / script.path.name
        shutil.copy2(script.path, target)
        copied.append(target)
        log.info(
            "cinema4d.script.deployed", source=str(script.path), destination=str(target)
        )

    return copied


def build_menu_actions_from_scripts(
    scripts: Iterable[Cinema4DScript],
    *,
    wrap_callback: (
        Callable[[str, Callable[[], None]], Callable[[], None]] | None
    ) = None,
) -> list["MenuAction"]:
    """Return :class:`MenuAction` objects for the provided scripts.

    The ``wrap_callback`` parameter allows callers to wrap the callable used for each
    script (for example, to add logging or error handling).
    """

    actions: list["MenuAction"] = []
    for script in scripts:
        callback = script.run
        if wrap_callback is not None:
            callback = wrap_callback(script.label, script.run)
        actions.append(
            MenuAction(
                script.label,
                callback,
                description=script.description
                or f"Run the {script.label} tool from the Cinema 4D scripts bundle.",
            )
        )
    return actions


# Imported lazily to avoid a hard dependency for non-UI consumers
from libraries.creative.dcc.ui_core import MenuAction  # noqa: E402  # isort: skip
