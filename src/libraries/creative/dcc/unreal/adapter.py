"""Modern OnePiece launcher panel for Unreal Engine."""

from __future__ import annotations

from typing import Any, Callable

import structlog

from libraries.creative.dcc.ui_core import (
    BaseMenu,
    BasePanel,
    MenuAction,
    require_qt_modules,
)

log = structlog.get_logger(__name__)


def _safe_action(label: str, func: Callable[[], None]) -> Callable[[], None]:
    def _wrapped() -> None:
        try:
            log.info("unreal.ui.action", action=label)
            func()
        except Exception:
            log.exception("unreal.ui.action_failed", action=label)

    return _wrapped


def _show_message(title: str, body: str) -> None:
    _, _, qt_widgets = require_qt_modules()
    dialog = qt_widgets.QMessageBox()
    dialog.setWindowTitle(title)
    dialog.setText(body)
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


_ACTIONS = (
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
)


def build_panel(parent: object | None = None) -> BasePanel:
    panel = BasePanel(
        "OnePiece for Unreal",
        "A modern control surface for cinematic workflows in Unreal Engine.",
        accent="#7AE3C3",
        parent=parent,
    )
    panel.add_actions(_ACTIONS)
    return panel


def build_menu(parent: object | None = None) -> Any:
    menu_builder = BaseMenu("OnePiece", accent="#7AE3C3")
    menu_builder.extend(_ACTIONS)
    return menu_builder.build_menu(parent)
