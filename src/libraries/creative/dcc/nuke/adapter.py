"""Modern OnePiece launcher panel for Nuke."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import structlog

from libraries.creative.dcc.ui_core import BaseMenu, BasePanel, MenuAction
from .deploy import get_script_library_path
from .script_launcher import (
    configure_script_launcher_defaults,
    discover_script_definitions,
)

log = structlog.get_logger(__name__)


SCRIPT_LIBRARY = get_script_library_path()
"""Packaged script directory used for menus and panels."""

configure_script_launcher_defaults(
    discover_script_definitions(SCRIPT_LIBRARY), SCRIPT_LIBRARY
)


def _safe_action(label: str, func: Callable[[], None]) -> Callable[[], None]:
    def _wrapped() -> None:
        try:
            log.info("nuke.ui.action", action=label)
            func()
        except Exception:
            log.exception("nuke.ui.action_failed", action=label)

    return _wrapped


def _show_script_launcher() -> None:
    from .script_launcher import ScriptLauncherWidget

    widget = ScriptLauncherWidget()
    widget.setWindowTitle("OnePiece Script Launcher")
    widget.show()


def _publish_default_camera() -> None:
    try:
        import nuke  # type: ignore
    except Exception:
        raise RuntimeError("Nuke is unavailable; cannot publish camera")

    from .publish_camera import publish_camera_from_nuke

    scene_path = Path(nuke.root().name())  # type: ignore[attr-defined]
    output = scene_path.with_suffix(".usd")
    publish_camera_from_nuke(nuke, "Camera1", output, {})


_ACTIONS = (
    MenuAction(
        "Launch Script Hub",
        _safe_action("script_launcher", _show_script_launcher),
        "Browse and run curated utility scripts inside Nuke.",
    ),
    MenuAction(
        "Publish Active Camera",
        _safe_action("publish_camera", _publish_default_camera),
        "Bake the current camera with lens metadata into USD.",
    ),
)


def _script_actions(script_directory: Path | None = None) -> list[MenuAction]:
    """Return actions for every bundled script in ``nuke/scripts``."""

    directory = script_directory or SCRIPT_LIBRARY
    definitions = discover_script_definitions(directory)
    actions: list[MenuAction] = []
    for definition in definitions:
        label = f"Run {definition.label}"
        description = definition.description or (
            f"Execute {definition.label} from {directory.name}."
        )
        actions.append(
            MenuAction(
                label, _safe_action(definition.label, definition.run), description
            )
        )
    return actions


def build_panel(parent: object | None = None) -> BasePanel:
    """Return a modern, accent-colored panel for Nuke utilities."""

    panel = BasePanel(
        "OnePiece for Nuke",
        "Curated utilities for lookdev, publishing and review inside Nuke.",
        parent=parent,
    )
    panel.add_section("OnePiece Actions", _ACTIONS)

    script_actions = _script_actions()
    if script_actions:
        panel.add_section("Nuke Scripts", script_actions)
    return panel


def build_menu(parent: object | None = None) -> Any:
    """Return a :class:`QMenu` mirroring the panel actions."""

    menu_builder = BaseMenu("OnePiece", accent="#8CE0FF")
    menu_builder.extend(_ACTIONS)
    menu_builder.extend(_script_actions())
    return menu_builder.build_menu(parent)
