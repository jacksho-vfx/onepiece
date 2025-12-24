"""Nuke specific DCC helpers."""

from importlib import import_module
from pathlib import Path
from typing import Any

from .deploy import (
    DEFAULT_DEPLOY_PATH,
    available_script_files,
    deploy_nuke_resources,
    get_resource_root,
    get_script_library_path,
)
from .script_launcher import (
    ScriptDefinition,
    ScriptLauncherWidget,
    configure_script_launcher_defaults,
    discover_script_definitions,
    register_script_launcher_panel,
)


def _nuke_module() -> Any:
    return import_module(".nuke", __name__)


def open_scene(path: Path) -> None:
    _nuke_module().open_scene(path)


def save_scene(path: Path | None = None) -> None:
    _nuke_module().save_scene(path)


def export_scene(path: Path) -> None:
    _nuke_module().export_scene(path)


def import_asset(path: Path) -> None:
    _nuke_module().import_asset(path)


__all__ = [
    "ScriptDefinition",
    "ScriptLauncherWidget",
    "DEFAULT_DEPLOY_PATH",
    "available_script_files",
    "deploy_nuke_resources",
    "get_resource_root",
    "get_script_library_path",
    "configure_script_launcher_defaults",
    "discover_script_definitions",
    "export_scene",
    "import_asset",
    "open_scene",
    "register_script_launcher_panel",
    "save_scene",
]
