"""
Maya DCC integration functions for OnePiece

Requires Maya's Python environment (pymel.core).
"""

import UPath
import structlog
import pymel.core as pm

log = structlog.get_logger(__name__)


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

    pm.openFile(str(path), force=True)  # type: ignore[no-untyped-call]
    log.info("maya_scene_opened", path=str(path))


def save_scene(path: UPath = None) -> None:
    """
    Save the current Maya scene.

    Args:
        path (UPath, optional): Path to save the scene. Saves current scene if None.
    """
    if path:
        pm.saveAs(str(path))
        log.info("maya_scene_saved_as", path=str(path))
    else:
        pm.saveFile()  # type: ignore[no-untyped-call]
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

    pm.importFile(str(path), type="mayaAscii" if path.endswith(".ma") else "mayaBinary")  # type: ignore[no-untyped-call]
    log.info("maya_asset_imported", path=str(path))


def export_scene(path: UPath) -> None:
    """
    Export the current Maya scene to a file.

    Args:
        path (UPath): Path to save the scene
    """
    if not path:
        raise ValueError("Path must be provided to export Maya scene")

    pm.exportAll(str(path))
    log.info("maya_scene_exported", path=str(path))
