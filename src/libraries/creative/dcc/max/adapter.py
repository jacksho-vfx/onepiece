"""Modern OnePiece launcher panel for Autodesk 3ds Max."""

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
            log.info("max.ui.action", action=label)
            func()
        except Exception:
            log.exception("max.ui.action_failed", action=label)

    return _wrapped


def _show_message(title: str, body: str) -> None:
    _, _, qt_widgets = require_qt_modules()
    dialog = qt_widgets.QMessageBox()
    dialog.setWindowTitle(title)
    dialog.setText(body)
    dialog.setIcon(qt_widgets.QMessageBox.Information)
    dialog.setStandardButtons(qt_widgets.QMessageBox.Ok)
    dialog.exec_()


def _open_material_library() -> None:
    _show_message(
        "Material Library",
        "Browse OnePiece procedural and scan-based materials without leaving"
        " your current workspace.",
    )


def _run_scene_optimizer() -> None:
    _show_message(
        "Scene Optimizer",
        "Run the OnePiece scene optimizer to collapse modifiers, freeze"
        " transforms, and prep for rendering.",
    )


def _export_to_unreal() -> None:
    _show_message(
        "Send to Unreal",
        "Package the current level or asset with datasmith-friendly settings"
        " and send it to Unreal Engine.",
    )


_ACTIONS = (
    MenuAction(
        "Material Library",
        _safe_action("material_library", _open_material_library),
        "Open curated shaders and presets for immediate assignment.",
    ),
    MenuAction(
        "Optimize Scene",
        _safe_action("scene_optimizer", _run_scene_optimizer),
        "Prepare the current scene for fast rendering and handoff.",
    ),
    MenuAction(
        "Send to Unreal",
        _safe_action("send_to_unreal", _export_to_unreal),
        "Package the scene using datasmith-ready presets.",
    ),
)


def build_panel(parent: object | None = None) -> BasePanel:
    panel = BasePanel(
        "OnePiece for 3ds Max",
        "Polished shortcuts for material lookdev, optimization, and handoff.",
        accent="#9F7AEA",
        parent=parent,
    )
    panel.add_actions(_ACTIONS)
    return panel


def build_menu(parent: object | None = None) -> Any:
    menu_builder = BaseMenu("OnePiece", accent="#9F7AEA")
    menu_builder.extend(_ACTIONS)
    return menu_builder.build_menu(parent)
