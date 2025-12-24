"""Modern OnePiece launcher panel for Autodesk 3ds Max."""

from __future__ import annotations

from functools import partial
import importlib
import importlib.util
from pathlib import Path
from typing import Any, Callable, Iterable

import structlog

from libraries.creative.dcc.max.deploy import (
    available_script_files,
    get_script_library_path,
)
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


def _show_message(title: str, *body_parts: str) -> None:
    _, _, qt_widgets = require_qt_modules()
    dialog = qt_widgets.QMessageBox()
    dialog.setWindowTitle(title)
    dialog.setText(" ".join(body_parts))
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


def _open_asset_browser() -> None:
    _show_message(
        "Asset Browser",
        "Browse show-approved assets, swap variants, and rewire references",
        " without leaving your current layout.",
    )


def _launch_handoff_checklist() -> None:
    _show_message(
        "Handoff Checklist",
        "Run through the handoff checklist to validate naming, frame ranges,",
        " and texture locations before packaging.",
    )


def _summarize_scene_state() -> None:
    _show_message(
        "Scene Snapshot",
        "Capture a quick summary of cameras, render layers, and shot metadata",
        " for supervisors.",
    )


_PIPELINE_ACTIONS: tuple[MenuAction, ...] = (
    MenuAction(
        "Asset Browser",
        _safe_action("asset_browser", _open_asset_browser),
        "Jump to approved assets and variants inside your current project.",
    ),
    MenuAction(
        "Handoff Checklist",
        _safe_action("handoff_checklist", _launch_handoff_checklist),
        "Step through naming, frame range, and texture checks before export.",
    ),
    MenuAction(
        "Scene Snapshot",
        _safe_action("scene_snapshot", _summarize_scene_state),
        "Generate a quick report of cameras, ranges, and render layers.",
    ),
)


def _pymxs_runtime() -> object | None:
    """Return the ``pymxs.runtime`` module when available."""

    if importlib.util.find_spec("pymxs") is None:
        log.warning("max.ui.pymxs_missing")
        return None

    pymxs = importlib.import_module("pymxs")
    return getattr(pymxs, "runtime", None)


def _extract_script_summary(path: Path) -> str | None:
    """Return the leading comment from a MaxScript file if present."""

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("--"):
                summary = stripped.lstrip("-").strip()
                return summary or None
            break
    except OSError:
        log.debug("max.ui.script_summary_unreadable", script=str(path))
    return None


def _run_maxscript(path: Path) -> None:
    """Execute a bundled MaxScript file with safety messaging."""

    runtime = _pymxs_runtime()
    if runtime is None:
        _show_message(
            "MaxScript unavailable",
            "The pymxs runtime could not be imported. Ensure you are running",
            " inside 3ds Max with Python enabled.",
        )
        return

    try:
        runtime.fileIn(str(path))  # type: ignore[attr-defined]
    except Exception:
        log.exception("max.ui.script_failed", script=str(path))
        _show_message(
            "Script failed",
            f"Unable to execute {path.name}. Check the MaxScript listener for",
            " more details.",
        )


def _script_actions(script_directory: Path | None = None) -> list[MenuAction]:
    """Return menu actions for every packaged MaxScript utility."""

    directory = script_directory or get_script_library_path()
    actions: list[MenuAction] = []
    for script in available_script_files(directory):
        label = script.stem.replace("_", " ").title()
        description = _extract_script_summary(script)
        callback = _safe_action(
            f"script::{script.stem}", partial(_run_maxscript, script)
        )
        actions.append(MenuAction(label, callback, description))
    return actions


def _all_menu_actions(script_directory: Path | None = None) -> Iterable[MenuAction]:
    return (*_ACTIONS, *_PIPELINE_ACTIONS, *_script_actions(script_directory))


def build_panel(parent: object | None = None) -> BasePanel:
    panel = BasePanel(
        "OnePiece for 3ds Max",
        (
            "Polished shortcuts for material lookdev, optimization, handoff, and "
            "bundled pipeline scripts."
        ),
        accent="#9F7AEA",
        parent=parent,
    )
    panel.add_section("Lookdev & Handoff", _ACTIONS)
    panel.add_section("Pipeline Intelligence", _PIPELINE_ACTIONS)

    scripts = _script_actions()
    if scripts:
        panel.add_section("Bundled MaxScripts", scripts)
    return panel


def build_menu(parent: object | None = None) -> Any:
    menu_builder = BaseMenu("OnePiece", accent="#9F7AEA")
    menu_builder.extend(_all_menu_actions())
    return menu_builder.build_menu(parent)
