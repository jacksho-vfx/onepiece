"""
Maya DCC integration functions for OnePiece

Requires Maya's Python environment (pymel.core).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict, cast

from upath import UPath
import structlog
import pymel.core as pm

log = structlog.get_logger(__name__)


def _resolve_pm_callable(name: str) -> Callable[..., None]:
    """Return a ``pymel.core`` callable, falling back to a stub when absent."""

    target = getattr(pm, name, None)
    if target is None:  # pragma: no cover - depends on Maya environment

        def _missing(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError(
                "pymel.core is missing the expected Maya command "
                f"'{name}'. Ensure Maya's Python package is available."
            )

        return _missing

    return cast(Callable[..., None], target)


_saveFile = _resolve_pm_callable("saveFile")
_openFile = _resolve_pm_callable("openFile")
_importFile = _resolve_pm_callable("importFile")
_exportAll = _resolve_pm_callable("exportAll")


def _save(**kwargs: Any) -> None:
    _saveFile(**kwargs)


def _open(path: UPath, **kwargs: Any) -> None:
    _openFile(str(path), **kwargs)


def _import(path: UPath, **kwargs: Any) -> None:
    _importFile(str(path), **kwargs)


def _export_all(path: UPath, **kwargs: Any) -> None:
    _exportAll(str(path), **kwargs)


def _remove_unused_references() -> Dict[str, int]:
    """Remove unused or broken file references from the scene."""

    removed = 0
    failed = 0

    for reference in pm.listReferences() or []:
        try:
            if reference.nodes():
                continue
        except RuntimeError as exc:  # pragma: no cover - depends on Maya state
            log.warning(
                "maya_reference_nodes_failed",
                reference=str(reference),
                error=str(exc),
            )
            failed += 1
            continue

        try:
            reference.remove()  # type: ignore[no-untyped-call]
            removed += 1
            log.info("maya_reference_removed", reference=str(reference))
        except RuntimeError as exc:  # pragma: no cover - depends on Maya state
            failed += 1
            log.warning(
                "maya_reference_remove_failed",
                reference=str(reference),
                error=str(exc),
            )

    return {"references_removed": removed, "references_failed": failed}


def _namespace_is_removable(namespace: str) -> bool:
    """Return True if the namespace has no dependency nodes."""

    try:
        dependency_nodes = (
            pm.namespaceInfo(namespace, listOnlyDependencyNodes=True) or []
        )
        child_namespaces = pm.namespaceInfo(namespace, listNamespace=True) or []
    except RuntimeError:  # pragma: no cover - requires Maya environment
        return False

    # Ignore Maya defaults
    child_namespaces = [
        child for child in child_namespaces if child not in {":", "UI", "shared"}
    ]

    return not dependency_nodes and not child_namespaces


def _cleanup_namespaces() -> Dict[str, int]:
    """Merge empty namespaces into root."""

    removed = 0
    failed = 0

    namespaces = pm.listNamespaces(recursive=True)
    # Remove deeper namespaces first so parents become empty.
    namespaces = sorted(namespaces, key=lambda ns: ns.count(":"), reverse=True)

    for namespace in namespaces:
        if namespace in {":", "UI", "shared"}:
            continue

        if not _namespace_is_removable(namespace):
            continue

        try:
            pm.namespace(removeNamespace=namespace)
            removed += 1
            log.info("maya_namespace_removed", namespace=namespace)
        except RuntimeError as exc:  # pragma: no cover - depends on Maya state
            failed += 1
            log.warning(
                "maya_namespace_remove_failed",
                namespace=namespace,
                error=str(exc),
            )

    return {"namespaces_removed": removed, "namespaces_failed": failed}


def _delete_unknown_nodes() -> Dict[str, int]:
    """Delete unknown/invalid nodes that bloat the file size."""

    unknown_types = ["unknown", "unknownDag", "unknownTransform"]
    try:
        unknown_nodes = pm.ls(type=unknown_types)
    except RuntimeError:  # pragma: no cover - depends on Maya state
        unknown_nodes = []

    deleted = 0

    if unknown_nodes:
        try:
            pm.delete(unknown_nodes)
            deleted = len(unknown_nodes)
            log.info("maya_unknown_nodes_deleted", count=deleted)
        except RuntimeError as exc:  # pragma: no cover - depends on Maya state
            log.warning("maya_unknown_nodes_delete_failed", error=str(exc))

    return {"unknown_nodes_deleted": deleted}


def _remove_empty_layers() -> Dict[str, int]:
    """Remove empty display and render layers."""

    display_removed = 0
    render_removed = 0

    for layer in pm.ls(type="displayLayer") or []:
        name = layer.name()
        if name == "defaultLayer":
            continue

        try:
            members: list[Any] = layer.listMembers() or []
        except RuntimeError:  # pragma: no cover - depends on Maya state
            members = []

        if members:
            continue

        try:
            pm.delete(layer)
            display_removed += 1
            log.info("maya_display_layer_removed", layer=name)
        except RuntimeError as exc:  # pragma: no cover - depends on Maya state
            log.warning("maya_display_layer_remove_failed", layer=name, error=str(exc))

    for layer in pm.ls(type="renderLayer") or []:
        name = layer.name()
        if name == "defaultRenderLayer":
            continue

        try:
            members = layer.listMembers() or []
        except RuntimeError:  # pragma: no cover - depends on Maya state
            members = []

        if members:
            continue

        try:
            pm.delete(layer)
            render_removed += 1
            log.info("maya_render_layer_removed", layer=name)
        except RuntimeError as exc:  # pragma: no cover - depends on Maya state
            log.warning("maya_render_layer_remove_failed", layer=name, error=str(exc))

    return {
        "display_layers_removed": display_removed,
        "render_layers_removed": render_removed,
    }


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

    import_kwargs: Dict[str, Any] = {}

    extension = path.suffix.lower()
    if extension == ".ma":
        import_kwargs["type"] = "mayaAscii"
    elif extension == ".mb":
        import_kwargs["type"] = "mayaBinary"
    elif extension == ".fbx":
        import_kwargs["type"] = "FBX"

    _import(path, **import_kwargs)
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


def cleanup_scene(
    remove_unused_references: bool = True,
    clean_namespaces: bool = True,
    optimize_layers: bool = True,
    prune_unknown_nodes: bool = True,
) -> Dict[str, int]:
    """Clean and optimize the open Maya scene.

    The cleanup routine removes unused references, collapses empty namespaces,
    purges empty display/render layers, and strips unknown nodes.  These steps
    help keep heavy animation scenes lean, reducing load times and preventing
    instability caused by orphaned data.

    Args:
        remove_unused_references: When ``True`` strip references that no longer
            contribute nodes to the scene.
        clean_namespaces: When ``True`` remove empty namespaces.
        optimize_layers: When ``True`` delete empty display and render layers.
        prune_unknown_nodes: When ``True`` delete unknown nodes that often make
            scenes unstable.

    Returns:
        Dictionary summarising the operations that were performed.  Keys are
        descriptive strings and values are counts of affected items.
    """

    stats: Dict[str, int] = {}

    if remove_unused_references:
        stats.update(_remove_unused_references())

    if clean_namespaces:
        stats.update(_cleanup_namespaces())

    if optimize_layers:
        stats.update(_remove_empty_layers())

    if prune_unknown_nodes:
        stats.update(_delete_unknown_nodes())

    log.info("maya_scene_cleanup_complete", **stats)
    return stats
