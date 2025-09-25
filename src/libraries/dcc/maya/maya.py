"""
Maya DCC integration functions for OnePiece

Requires Maya's Python environment (pymel.core).
"""

from typing import Any, cast, Callable

from upath import UPath
import structlog
import pymel.core as pm

log = structlog.get_logger(__name__)


_saveFile = cast(Callable[..., None], pm.saveFile)
_openFile = cast(Callable[..., None], pm.openFile)
_importFile = cast(Callable[..., None], pm.importFile)
_exportAll = cast(Callable[..., None], pm.exportAll)


def _save(**kwargs: Any) -> None:
    pm.saveFile(**kwargs)


def _open(path: UPath, **kwargs: Any) -> None:
    pm.openFile(str(path), **kwargs)


def _import(path: UPath, **kwargs: Any) -> None:
    pm.importFile(str(path), **kwargs)


def _export_all(path: UPath, **kwargs: Any) -> None:
    pm.exportAll(str(path), **kwargs)


# --------------------------------------------------------------------------- #
# Scene Operations
# --------------------------------------------------------------------------- #
def open_scene(path: UPath) -> None:
    """
    Open a Maya scene file (.ma or .mb).

    Args:
        path (UPath): Path to the Maya scene
    """
    if not path.exists():
        log.error("maya_open_scene_failed", path=str(path))
        raise FileNotFoundError(f"Maya scene not found: {str(path)}")

    _open(path, force=True)
    log.info("maya_scene_opened", path=str(path))


def save_scene(path: UPath) -> None:
    """
    Save the current Maya scene.

    Args:
        path (UPath, optional): Path to save the scene. Saves current scene if None.
    """
    if path:
        pm.saveAs(str(path))
        log.info("maya_scene_saved_as", path=str(path))
    else:
        _save(force=True)
        log.info("maya_scene_saved", path="current")


# --------------------------------------------------------------------------- #
# Asset Operations
# --------------------------------------------------------------------------- #
def import_asset(path: UPath) -> None:
    """
    Import an asset or scene into the current Maya scene.

    Args:
        path (UPath): Path to the Maya file (.ma, .mb, or FBX)
    """
    if not path.exists():
        log.error("maya_import_asset_failed", path=str(path))
        raise FileNotFoundError(f"Maya asset not found: {str(path)}")

    _import(path, type="mayaAscii" if path.name.endswith(".ma") else "mayaBinary")
    log.info("maya_asset_imported", path=str(path))


def export_scene(path: UPath) -> None:
    """
    Export the current Maya scene to a file.

    Args:
        path (UPath): Path to save the scene
    """
    if not path:
        raise ValueError("Path must be provided to export Maya scene")

    _export_all(path, force=True, type="mayaAscii")
    log.info("maya_scene_exported", path=str(path))
