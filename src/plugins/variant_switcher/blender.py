from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from libraries.creative.dcc.models import SupportedDCC

from .core import VariantActivation, VariantSet
from .plugin import list_variants as _list_variants, switch_variant as _switch_variant

DCC = SupportedDCC.BLENDER


def list_variants(
    stage_path: str | Path, *, search_paths: Sequence[Path] | None = None
) -> tuple[VariantSet, ...]:
    """List variants for Blender USD stages."""

    return _list_variants(stage_path, search_paths=search_paths)


def switch_variant(
    stage_path: str | Path,
    set_name: str,
    selection: str,
    *,
    search_paths: Sequence[Path] | None = None,
    refresh_viewport: Callable[[], None] | None = None,
) -> VariantActivation:
    """Switch a Blender stage variant and refresh viewport renders."""

    refresh = refresh_viewport or _noop_refresh
    return _switch_variant(
        stage_path,
        set_name,
        selection,
        search_paths=search_paths,
        refresh_viewport=refresh,
    )


def _noop_refresh() -> None:
    return None


__all__ = ["DCC", "list_variants", "switch_variant"]
