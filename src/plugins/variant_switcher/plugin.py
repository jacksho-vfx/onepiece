from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from .core import StageVariants, VariantActivation, VariantSet


def list_variants(
    stage_path: str | Path, *, search_paths: Sequence[Path] | None = None
) -> tuple[VariantSet, ...]:
    """Return the variant sets available on the given USD stage."""

    return StageVariants(Path(stage_path), search_paths=search_paths).list_variants()


def switch_variant(
    stage_path: str | Path,
    set_name: str,
    selection: str,
    *,
    search_paths: Sequence[Path] | None = None,
    refresh_viewport: Callable[[], None] | None = None,
) -> VariantActivation:
    """Activate a variant option while relinking payload dependencies."""

    switcher = StageVariants(Path(stage_path), search_paths=search_paths)
    return switcher.activate(
        set_name,
        selection,
        refresh_viewport=refresh_viewport,
    )


__all__ = ["list_variants", "switch_variant", "VariantActivation", "VariantSet"]
