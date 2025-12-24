"""Nuke menu entry point for the OnePiece toolkit.

This file is copied into a Nuke plugin directory by the deployment CLI.
It wires up the Script Launcher panel, a modern OnePiece panel and a
scripts submenu that exposes every bundled utility.
"""

from __future__ import annotations

from pathlib import Path

import nuke  # type: ignore

from libraries.creative.dcc.nuke.adapter import build_menu, build_panel
from libraries.creative.dcc.nuke.script_launcher import (
    configure_script_launcher_defaults,
    discover_script_definitions,
    register_script_launcher_panel,
)

RESOURCE_ROOT = Path(__file__).parent
SCRIPTS_ROOT = RESOURCE_ROOT / "scripts"
SCRIPT_DEFINITIONS = discover_script_definitions(SCRIPTS_ROOT)

configure_script_launcher_defaults(SCRIPT_DEFINITIONS, SCRIPTS_ROOT)
PANEL_ID = register_script_launcher_panel(
    scripts=SCRIPT_DEFINITIONS, script_directory=SCRIPTS_ROOT
)


def _show_panel() -> None:
    panel = build_panel()
    panel.show()


def _show_script_launcher() -> None:
    import nukescripts  # type: ignore

    panels = getattr(nukescripts, "panels", nukescripts)
    restore = getattr(panels, "restorePanel")
    restore(PANEL_ID)


def _register_menu() -> None:
    root_menu = nuke.menu("Nuke")  # type: ignore[attr-defined]
    onepiece_menu = root_menu.addMenu("OnePiece")

    onepiece_menu.addCommand("Open OnePiece Panel", _show_panel)
    onepiece_menu.addCommand("Open Script Launcher", _show_script_launcher)

    qmenu = build_menu()
    qmenu.triggered.connect(lambda action: action.trigger())  # type: ignore[arg-type]
    for action in qmenu.actions():  # type: ignore[attr-defined]
        label = action.text()
        onepiece_menu.addCommand(label, action.trigger)

    scripts_menu = onepiece_menu.addMenu("Scripts")
    for definition in SCRIPT_DEFINITIONS:
        scripts_menu.addCommand(definition.label, definition.run)


_register_menu()
