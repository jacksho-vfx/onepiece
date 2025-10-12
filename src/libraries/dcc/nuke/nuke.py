"""
Nuke DCC integration functions for OnePiece

Requires Nuke’s Python environment.
"""

from pathlib import Path

import nuke
import structlog

log = structlog.get_logger(__name__)


# --------------------------------------------------------------------------- #
# Scene Operations
# --------------------------------------------------------------------------- #
def open_scene(path: Path) -> None:
    """
    Open a Nuke script (.nk).

    Args:
        path (UPath): Path to the .nk file
    """
    if not path.exists():
        log.error("nuke_open_scene_failed", path=str(path))
        raise FileNotFoundError(f"Nuke script not found: {str(path)}")

    nuke.scriptOpen(str(path))
    log.info("nuke_scene_opened", path=str(path))


def save_scene(path: Path | None = None) -> None:
    """
    Save the current Nuke script.

    Args:
        path: Optional path where the script should be written.  When ``None`` the
            currently open script is saved in-place.
    """
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        nuke.scriptSaveAs(str(path))
        log.info("nuke_scene_saved_as", path=str(path))
    else:
        nuke.scriptSave()
        log.info("nuke_scene_saved", path="current")


def export_scene(path: Path) -> None:
    """
    Export the current Nuke script to a specific file.

    Args:
        path (UPath): Path to save the script
    """
    if not path:
        raise ValueError("Path must be provided to export Nuke script")

    path.parent.mkdir(parents=True, exist_ok=True)
    nuke.scriptSaveAs(str(path))
    log.info("nuke_scene_exported", path=str(path))


# --------------------------------------------------------------------------- #
# Asset Operations
# --------------------------------------------------------------------------- #
def import_asset(path: Path) -> None:
    """
    Import a Nuke node tree from another .nk script.

    Args:
        path (UPath): Path to the .nk file to import
    """
    if not path.exists():
        log.error("nuke_import_asset_failed", path=str(path))
        raise FileNotFoundError(f"Nuke script not found: {str(path)}")

    nuke.nodePaste(str(path))
    log.info("nuke_asset_imported", path=str(path))
