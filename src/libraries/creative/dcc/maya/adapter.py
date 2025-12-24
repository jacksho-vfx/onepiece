"""Modern OnePiece launcher panel for Autodesk Maya."""

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
            log.info("maya.ui.action", action=label)
            func()
        except Exception:
            log.exception("maya.ui.action_failed", action=label)

    return _wrapped


def _show_message(title: str, body: str) -> None:
    _, _, qt_widgets = require_qt_modules()
    dialog = qt_widgets.QMessageBox()
    dialog.setWindowTitle(title)
    dialog.setText(body)
    dialog.setIcon(qt_widgets.QMessageBox.Information)
    dialog.setStandardButtons(qt_widgets.QMessageBox.Ok)
    dialog.exec_()


def _open_playblast_tool() -> None:
    _show_message(
        "Playblast Automation",
        "Kick off the PlayblastAutomationTool from the OnePiece shelf to"
        " generate review-ready clips with studio defaults.",
    )


def _open_animation_debugger() -> None:
    _show_message(
        "Animation Debugger",
        "Run the animation diagnostic suite to scan constraints, caches, and"
        " frame ranges before publishing.",
    )


def _launch_character_selector() -> None:
    from .character_selector import CharacterSelectorPanel

    CharacterSelectorPanel.show_panel()


_ACTIONS = (
    MenuAction(
        "Generate Playblast",
        _safe_action("playblast", _open_playblast_tool),
        "Render a beautifully formatted playblast with studio defaults.",
    ),
    MenuAction(
        "Animation Debugger",
        _safe_action("animation_debugger", _open_animation_debugger),
        "Scan the current scene for animation issues before publishing.",
    ),
    MenuAction(
        "Character Selector",
        _safe_action("character_selector", _launch_character_selector),
        "Jump to key character rigs instantly.",
    ),
)


def build_panel(parent: object | None = None) -> BasePanel:
    panel = BasePanel(
        "OnePiece for Maya",
        "Elegant quick-launch access to your go-to Maya production tools.",
        accent="#FF8B6B",
        parent=parent,
    )
    panel.add_actions(_ACTIONS)
    return panel


def build_menu(parent: object | None = None) -> Any:
    menu_builder = BaseMenu("OnePiece", accent="#FF8B6B")
    menu_builder.extend(_ACTIONS)
    return menu_builder.build_menu(parent)
