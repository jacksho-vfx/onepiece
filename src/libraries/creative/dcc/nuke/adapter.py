"""Modern OnePiece launcher panel for Nuke."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import structlog

from libraries.creative.dcc.ui_core import BaseMenu, BasePanel, MenuAction

log = structlog.get_logger(__name__)


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


def build_panel(parent: object | None = None) -> BasePanel:
    """Return a modern, accent-colored panel for Nuke utilities."""

    panel = BasePanel(
        "OnePiece for Nuke",
        "Curated utilities for lookdev, publishing and review inside Nuke.",
        parent=parent,
    )
    panel.add_actions(_ACTIONS)
    return panel


def build_menu(parent: object | None = None) -> Any:
    """Return a :class:`QMenu` mirroring the panel actions."""

    menu_builder = BaseMenu("OnePiece", accent="#8CE0FF")
    menu_builder.extend(_ACTIONS)
    return menu_builder.build_menu(parent)
