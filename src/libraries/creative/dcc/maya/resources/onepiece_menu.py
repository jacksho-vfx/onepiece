"""Create a OnePiece menu and panel inside Maya.

The panel and menu dynamically discover Python scripts stored alongside this
module in ``scripts/``. Each script is executed when its corresponding menu
item or panel button is selected.
"""

from __future__ import annotations

import traceback
from functools import partial
from pathlib import Path
from typing import Callable

import maya.cmds as cmds  # type: ignore

HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE / "scripts"
MENU_NAME = "OnePieceMenu"
PANEL_NAME = "OnePiecePanel"


def _discover_scripts() -> list[Path]:
    """Return sorted script files that should appear in the UI."""

    if not SCRIPTS_DIR.exists():
        return []

    return sorted(
        path
        for path in SCRIPTS_DIR.iterdir()
        if path.is_file() and path.suffix == ".py"
    )


def _friendly_label(script_path: Path) -> str:
    stem = script_path.stem.replace("_", " ")
    return stem[:1].upper() + stem[1:]


def _load_script(script_path: Path) -> Callable[[], None]:
    """Return a callable that executes *script_path* in its own module."""

    def _runner() -> None:
        namespace = {
            "__file__": str(script_path),
            "__name__": script_path.stem,
        }
        try:
            with script_path.open("r", encoding="utf-8") as handle:
                exec(compile(handle.read(), str(script_path), "exec"), namespace)
        except Exception:  # pragma: no cover - Maya execution environment only
            traceback.print_exc()

    return _runner


def run_script_by_name(script_name: str) -> None:
    """Execute a discovered script by filename."""

    script_path = SCRIPTS_DIR / script_name
    if not script_path.exists():
        cmds.warning(f"Script '{script_name}' not found in {SCRIPTS_DIR}")
        return

    _load_script(script_path)()


def build_menu(parent: str = "MayaWindow") -> str:
    """Create or rebuild the OnePiece Maya menu."""

    if cmds.menu(MENU_NAME, exists=True):
        cmds.deleteUI(MENU_NAME)

    menu = str(cmds.menu(MENU_NAME, label="OnePiece", parent=parent, tearOff=True))
    cmds.menuItem(label="Open OnePiece Panel", command=lambda *_: open_panel())
    cmds.menuItem(divider=True)

    for script_path in _discover_scripts():
        cmds.menuItem(
            parent=menu,
            label=_friendly_label(script_path),
            command=lambda *_args, name=script_path.name: run_script_by_name(name),
        )

    if not _discover_scripts():
        cmds.menuItem(parent=menu, label="No bundled scripts found", enable=False)

    return menu


def open_panel() -> str:
    """Create a dockable panel listing all available scripts."""

    if cmds.workspaceControl(PANEL_NAME, exists=True):
        cmds.deleteUI(PANEL_NAME)

    control = str(
        cmds.workspaceControl(
            PANEL_NAME,
            label="OnePiece Toolkit",
            retain=False,
            loadImmediately=True,
        )
    )

    column = cmds.columnLayout(adjustableColumn=True, rowSpacing=6, parent=control)
    cmds.text(label="OnePiece Maya Scripts", align="center", parent=column)
    cmds.separator(parent=column, height=6, style="in")

    scripts = _discover_scripts()
    for script_path in scripts:
        cmds.button(
            parent=column,
            label=_friendly_label(script_path),
            command=partial(run_script_by_name, script_path.name),
            height=28,
        )

    if not scripts:
        cmds.text(label="No scripts were found in the OnePiece package.", parent=column)

    cmds.setParent("..")
    return control


def bootstrap() -> None:
    """Add the OnePiece menu and panel hooks to the running Maya session."""

    build_menu()


__all__ = ["build_menu", "bootstrap", "open_panel", "run_script_by_name"]
