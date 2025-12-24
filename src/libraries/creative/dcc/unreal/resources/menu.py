"""Menu bootstrap copied into Unreal plugin directories by the CLI."""

from __future__ import annotations

from pathlib import Path

import structlog

from libraries.creative.dcc.unreal.adapter import build_menu, build_panel
from libraries.creative.dcc.unreal.deploy import get_script_library_path
from libraries.creative.dcc.unreal.scripts import discover_unreal_scripts

log = structlog.get_logger(__name__)

RESOURCE_ROOT = Path(__file__).parent
SCRIPTS_ROOT = get_script_library_path()
SCRIPT_DEFINITIONS = discover_unreal_scripts(SCRIPTS_ROOT)

try:  # pragma: no cover - relies on Unreal runtime
    import unreal  # type: ignore
except Exception:  # pragma: no cover - depends on host
    unreal = None  # type: ignore


def _show_panel() -> None:
    panel = build_panel()
    panel.show()


def _register_menu() -> None:
    if unreal is None:  # pragma: no cover - depends on Unreal runtime
        log.warning("unreal.menu.unavailable", reason="Unreal module not importable")
        return

    menus = getattr(unreal, "ToolMenus", None)
    if menus is None:  # pragma: no cover - depends on Unreal runtime
        log.warning("unreal.menu.missing_toolmenus")
        return

    registry = menus.get()
    level_menu = registry.find_menu("LevelEditor.MainMenu.Tools")
    if level_menu is None:
        log.warning("unreal.menu.missing_parent", menu="LevelEditor.MainMenu.Tools")
        return

    onepiece_menu = registry.add_menu("LevelEditor.MainMenu.Tools.OnePiece")
    onepiece_menu.add_menu_entry_from_command()
    panel_action = onepiece_menu.add_menu_entry("OnePiece", "Open Panel")
    panel_action.set_label("Open OnePiece Panel")
    panel_action.set_string_field("command", "open_onepiece_panel")

    qmenu = build_menu()
    qmenu.triggered.connect(lambda action: action.trigger())  # type: ignore[arg-type]
    for action in qmenu.actions():  # type: ignore[attr-defined]
        label = action.text()
        entry = onepiece_menu.add_menu_entry(label, label)
        entry.set_label(label)
        entry.set_string_field("command", label)

    scripts_menu = registry.add_menu("LevelEditor.MainMenu.Tools.OnePiece.Scripts")
    for definition in SCRIPT_DEFINITIONS:
        entry = scripts_menu.add_menu_entry(definition.label, definition.label)
        entry.set_label(definition.label)
        entry.set_string_field("path", str(definition.path))

    registry.refresh_all_widgets()


_register_menu()
