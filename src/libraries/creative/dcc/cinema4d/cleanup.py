"""Helpers for cleaning up the active Cinema 4D scene."""

from __future__ import annotations

from collections.abc import Iterable

import structlog

try:  # pragma: no cover - Cinema 4D is not available in CI
    import c4d  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - replaced by tests stubs
    c4d = None  # type: ignore


log = structlog.get_logger(__name__)


class _RemovalError(RuntimeError):
    """Raised when the cleanup helpers cannot access Cinema 4D APIs."""


def _require_module(module: object | None) -> object:
    if module is None:
        raise _RemovalError(
            "Cinema 4D Python API is unavailable; cannot clean the active scene"
        )
    return module


def _resolve_document(module: object, document: object | None) -> object:
    if document is not None:
        return document

    documents = getattr(module, "documents", None)
    get_active = getattr(documents, "GetActiveDocument", None)
    if callable(get_active):
        active_document = get_active()
        if active_document is not None:
            return active_document

    raise _RemovalError("No active Cinema 4D document is available for cleanup")


def _iter_hierarchy(root: object | None) -> Iterable[object]:
    if root is None:
        return

    stack: list[object] = []
    current = root
    while current is not None:
        yield current
        child = getattr(current, "GetDown", None)
        next_node = getattr(current, "GetNext", None)

        child_obj = child() if callable(child) else None
        next_obj = next_node() if callable(next_node) else None

        if next_obj is not None:
            stack.append(next_obj)
        if child_obj is not None:
            current = child_obj
            continue
        current = stack.pop() if stack else None


def _iter_scene_objects(document: object) -> list[object]:
    get_first_object = getattr(document, "GetFirstObject", None)
    if not callable(get_first_object):
        return []
    first = get_first_object()
    return list(_iter_hierarchy(first))


def _iter_layer_objects(document: object) -> list[object]:
    get_root = getattr(document, "GetLayerObjectRoot", None)
    if not callable(get_root):
        return []
    root = get_root()
    if root is None:
        return []
    layers = list(_iter_hierarchy(root))
    # The layer root is a container that should never be removed.
    return [layer for layer in layers if not _is_root_layer(layer)]


def _iter_materials(document: object) -> list[object]:
    materials: list[object] = []
    get_first_material = getattr(document, "GetFirstMaterial", None)
    if callable(get_first_material):
        material = get_first_material()
        visited: set[int] = set()
        while material is not None and id(material) not in visited:
            materials.append(material)
            visited.add(id(material))
            get_next = getattr(material, "GetNext", None)
            material = get_next() if callable(get_next) else None

    get_materials = getattr(document, "GetMaterials", None)
    if callable(get_materials):
        for material in get_materials():
            if material not in materials:
                materials.append(material)

    return materials


def _remove_item(item: object, document: object, remover_name: str) -> bool:
    remove = getattr(item, "Remove", None)
    if callable(remove):
        remove()
        return True

    remover = getattr(document, remover_name, None)
    if callable(remover):
        remover(item)
        return True
    return False


def _collect_material_assignments(objects: Iterable[object]) -> set[int]:
    assigned: set[int] = set()
    for obj in objects:
        get_tags = getattr(obj, "GetTags", None)
        tags = get_tags() if callable(get_tags) else getattr(obj, "tags", None)
        if not tags:
            continue
        for tag in tags:
            get_material = getattr(tag, "GetMaterial", None)
            material = get_material() if callable(get_material) else None
            if material is not None:
                assigned.add(id(material))
    return assigned


def _remove_unused_materials(document: object) -> int:
    materials = _iter_materials(document)
    used_material_ids = _collect_material_assignments(_iter_scene_objects(document))

    removed = 0
    for material in materials:
        if id(material) in used_material_ids:
            continue
        if _remove_item(material, document, "RemoveMaterial"):
            removed += 1
    return removed


def _has_children(node: object) -> bool:
    get_down = getattr(node, "GetDown", None)
    if callable(get_down):
        return get_down() is not None
    children = getattr(node, "children", None)
    return bool(children)


def _is_null_object(obj: object, module: object) -> bool:
    null_id = getattr(module, "Onull", None)
    check_type = getattr(obj, "CheckType", None)
    if callable(check_type) and null_id is not None:
        try:
            return bool(check_type(null_id))
        except TypeError:
            pass

    get_type = getattr(obj, "GetType", None)
    if callable(get_type) and null_id is not None:
        return bool(get_type() == null_id)

    return bool(getattr(obj, "is_null", False))


def _is_hidden(obj: object, module: object) -> bool:
    mode_off = getattr(module, "MODE_OFF", None)
    get_editor_mode = getattr(obj, "GetEditorMode", None)
    get_render_mode = getattr(obj, "GetRenderMode", None)
    if callable(get_editor_mode) and callable(get_render_mode) and mode_off is not None:
        try:
            return bool(
                get_editor_mode() == mode_off and get_render_mode() == mode_off
            )
        except TypeError:
            return False
    hidden_flag = getattr(obj, "is_hidden", None)
    if isinstance(hidden_flag, bool):
        return hidden_flag
    return False


def _remove_empty_nulls(document: object, module: object) -> int:
    removed = 0
    for obj in list(_iter_scene_objects(document)):
        if not _is_null_object(obj, module):
            continue
        if _has_children(obj):
            continue
        if _remove_item(obj, document, "RemoveObject"):
            removed += 1
    return removed


def _remove_hidden_singletons(document: object, module: object) -> int:
    removed = 0
    for obj in list(_iter_scene_objects(document)):
        if not _is_hidden(obj, module):
            continue
        if _has_children(obj):
            continue
        if _remove_item(obj, document, "RemoveObject"):
            removed += 1
    return removed


def _is_root_layer(layer: object) -> bool:
    is_root = getattr(layer, "IsRootLayer", None)
    if callable(is_root):
        try:
            return bool(is_root())
        except TypeError:
            return False
    return bool(getattr(layer, "is_root", False))


def _layer_children(layer: object) -> list[object]:
    children: list[object] = []
    get_down = getattr(layer, "GetDown", None)
    if callable(get_down):
        child = get_down()
        while child is not None:
            children.append(child)
            get_next = getattr(child, "GetNext", None)
            child = get_next() if callable(get_next) else None
    return children


def _collect_used_layers(document: object) -> set[int]:
    used: set[int] = set()
    for obj in _iter_scene_objects(document):
        get_layer = getattr(obj, "GetLayerObject", None)
        layer = get_layer() if callable(get_layer) else getattr(obj, "layer", None)
        if layer is not None:
            used.add(id(layer))
    for material in _iter_materials(document):
        get_layer = getattr(material, "GetLayerObject", None)
        layer = get_layer() if callable(get_layer) else getattr(material, "layer", None)
        if layer is not None:
            used.add(id(layer))
    return used


def _remove_unused_layers(document: object) -> int:
    layers = _iter_layer_objects(document)
    if not layers:
        return 0

    used_layers = _collect_used_layers(document)
    removed = 0
    for layer in layers:
        if _layer_children(layer):
            continue
        if id(layer) in used_layers:
            continue
        if _remove_item(layer, document, "RemoveLayer"):
            removed += 1
    return removed


def cleanup_scene(
    document: object | None = None,
    *,
    remove_unused_materials: bool = True,
    remove_empty_nulls: bool = True,
    remove_hidden_singletons: bool = True,
    remove_unused_layers: bool = True,
    module: object | None = None,
) -> dict[str, int]:
    """Clean the active Cinema 4D scene and report the performed operations."""

    resolved_module = _require_module(module or c4d)
    resolved_document = _resolve_document(resolved_module, document)

    stats = {
        "removed_materials": 0,
        "removed_empty_nulls": 0,
        "removed_hidden_singletons": 0,
        "removed_layers": 0,
    }

    if remove_unused_materials:
        stats["removed_materials"] = _remove_unused_materials(resolved_document)

    if remove_empty_nulls:
        stats["removed_empty_nulls"] = _remove_empty_nulls(
            resolved_document, resolved_module
        )

    if remove_hidden_singletons:
        stats["removed_hidden_singletons"] = _remove_hidden_singletons(
            resolved_document, resolved_module
        )

    if remove_unused_layers:
        stats["removed_layers"] = _remove_unused_layers(resolved_document)

    log.info("cinema4d_scene_cleanup_summary", **stats)
    return stats


__all__ = ["cleanup_scene"]
