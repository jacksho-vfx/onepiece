"""Modern OnePiece launcher panel for Cinema 4D."""

from __future__ import annotations

from typing import Any, Callable

import structlog

from libraries.creative.dcc.ui_core import (
    BaseMenu,
    BasePanel,
    MenuAction,
    require_qt_modules,
)

from .script_library import (
    build_menu_actions_from_scripts,
    default_script_directory,
    discover_cinema4d_scripts,
)

log = structlog.get_logger(__name__)


def _safe_action(label: str, func: Callable[[], None]) -> Callable[[], None]:
    def _wrapped() -> None:
        try:
            log.info("cinema4d.ui.action", action=label)
            func()
        except Exception:
            log.exception("cinema4d.ui.action_failed", action=label)

    return _wrapped


def _show_message(title: str, body: str) -> None:
    _, _, qt_widgets = require_qt_modules()
    dialog = qt_widgets.QMessageBox()
    dialog.setWindowTitle(title)
    dialog.setText(body)
    dialog.setIcon(qt_widgets.QMessageBox.Information)
    dialog.setStandardButtons(qt_widgets.QMessageBox.Ok)
    dialog.exec_()


def _cleanup_scene() -> None:
    from .cleanup import cleanup_scene

    stats = cleanup_scene()
    log.info("cinema4d.cleaned", stats=stats)


def _publish_active_camera() -> None:
    _show_message(
        "Publish Active Camera",
        "Export the focused camera through the OnePiece USD publisher"
        " inside Cinema 4D's pipeline menu.",
    )


def _launch_command_panel() -> None:
    from .panel import CommandPanel

    panel = CommandPanel(title="OnePiece Commands")
    panel.show()


def _script_actions() -> tuple[MenuAction, ...]:
    scripts = discover_cinema4d_scripts(default_script_directory())
    return tuple(build_menu_actions_from_scripts(scripts, wrap_callback=_safe_action))


_ACTIONS = (
    MenuAction(
        "Cleanup Scene",
        _safe_action("cleanup", _cleanup_scene),
        "Remove stray layers, materials, and hidden nodes before publishing.",
    ),
    MenuAction(
        "Publish Active Camera",
        _safe_action("publish_camera", _publish_active_camera),
        "Export the currently selected camera with baked metadata.",
    ),
    MenuAction(
        "Command Palette",
        _safe_action("command_palette", _launch_command_panel),
        "Open a quick-access palette of render and pipeline helpers.",
    ),
)


def build_panel(parent: object | None = None) -> BasePanel:
    panel = BasePanel(
        "OnePiece for Cinema 4D",
        "Elegant quick-launch controls for scene cleanup and publishing.",
        accent="#F6C343",
        parent=parent,
    )
    panel.add_section("Core Actions", _ACTIONS)

    scripts = _script_actions()
    if scripts:
        panel.add_section("Cinema 4D Scripts", scripts)
    return panel


def build_menu(parent: object | None = None) -> Any:
    menu_builder = BaseMenu("OnePiece", accent="#F6C343")
    menu_builder.extend(_ACTIONS)

    script_actions = _script_actions()
    if script_actions:
        menu_builder.extend(script_actions)
    return menu_builder.build_menu(parent)
