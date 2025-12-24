"""Modern OnePiece launcher panel for Unreal Engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import structlog

from libraries.creative.dcc.ui_core import (
    BaseMenu,
    BasePanel,
    MenuAction,
    require_qt_modules,
)
from .deploy import get_script_library_path
from .scripts import discover_unreal_scripts

log = structlog.get_logger(__name__)


def _safe_action(label: str, func: Callable[[], None]) -> Callable[[], None]:
    def _wrapped() -> None:
        try:
            log.info("unreal.ui.action", action=label)
            func()
        except Exception:
            log.exception("unreal.ui.action_failed", action=label)

    return _wrapped


def _show_message(title: str, *body: str) -> None:
    _, _, qt_widgets = require_qt_modules()
    dialog = qt_widgets.QMessageBox()
    dialog.setWindowTitle(title)
    dialog.setText(" ".join(body))
    dialog.setIcon(qt_widgets.QMessageBox.Information)
    dialog.setStandardButtons(qt_widgets.QMessageBox.Ok)
    dialog.exec_()


def _open_content_browser() -> None:
    _show_message(
        "Content Browser",
        "Access curated project content collections directly from the OnePiece"
        " panel to accelerate look development and layout.",
    )


def _run_validation_suite() -> None:
    _show_message(
        "Project Validation",
        "Run the OnePiece validation blueprint to ensure lighting, rendering,"
        " and asset conventions are followed before packaging.",
    )


def _launch_sequence_tools() -> None:
    _show_message(
        "Sequencer Tools",
        "Jump into cinematic controls for shot templates, camera bookmarks,"
        " and render queue presets.",
    )


def _sync_published_packages() -> None:
    _show_message(
        "Sync from Publish",
        "Pull the latest OnePiece packages into your Unreal project content directory",
        " so environments stay consistent across DCCs.",
    )


def _inspect_level_health() -> None:
    _show_message(
        "Level Health",
        "Review world partition, LOD coverage, and map warnings in one place.",
    )


def _open_python_console() -> None:
    _show_message(
        "Python Console",
        "Open the embedded Unreal Python console preloaded with OnePiece helpers",
        " for quick automation and debugging.",
    )


def _script_actions(script_directory: Path | None = None) -> list[MenuAction]:
    directory = script_directory or get_script_library_path()
    actions: list[MenuAction] = []
    for definition in discover_unreal_scripts(directory):
        description = definition.description or (
            f"Execute {definition.label} from the packaged Unreal scripts library."
        )
        actions.append(
            MenuAction(
                f"Run {definition.label}",
                _safe_action(definition.label, definition.run),
                description,
            )
        )
    return actions


_CORE_ACTIONS = (
    MenuAction(
        "Open Content Browser",
        _safe_action("content_browser", _open_content_browser),
        "Navigate curated assets and materials without leaving the viewport.",
    ),
    MenuAction(
        "Validate Project",
        _safe_action("validation", _run_validation_suite),
        "Check level, lighting, and rendering settings against studio defaults.",
    ),
    MenuAction(
        "Sequencer Toolkit",
        _safe_action("sequencer", _launch_sequence_tools),
        "Access cinematic presets, bookmarks, and render queue helpers.",
    ),
    MenuAction(
        "Sync Publish Packages",
        _safe_action("sync_publish", _sync_published_packages),
        "Mirror the latest Maya and Houdini drops directly into your content browser.",
    ),
    MenuAction(
        "Level Health Report",
        _safe_action("level_health", _inspect_level_health),
        "Run non-destructive checks for map warnings, partition coverage, and LOD gaps.",
    ),
    MenuAction(
        "Open Python Console",
        _safe_action("python_console", _open_python_console),
        "Launch a Python console preloaded with OnePiece utility imports.",
    ),
)


def build_panel(parent: object | None = None) -> BasePanel:
    panel = BasePanel(
        "OnePiece for Unreal",
        "A modern control surface for cinematic workflows in Unreal Engine.",
        accent="#7AE3C3",
        parent=parent,
    )
    panel.add_section("Production Workflows", _CORE_ACTIONS)
    script_actions = _script_actions()
    if script_actions:
        panel.add_section("Automation Scripts", script_actions)
    return panel


def build_menu(parent: object | None = None) -> Any:
    menu_builder = BaseMenu("OnePiece", accent="#7AE3C3")
    menu_builder.extend(_CORE_ACTIONS)
    menu_builder.extend(_script_actions())
    return menu_builder.build_menu(parent)
