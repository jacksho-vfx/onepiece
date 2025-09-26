"""Helpers for validating and inferring Digital Content Creation tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from libraries.dcc.dcc_client import SupportedDCC

__all__ = ["SupportedDCC", "validate_dcc", "detect_dcc_from_file"]


_EXTENSION_MAP: dict[str, SupportedDCC] = {
    ".ma": SupportedDCC.MAYA,
    ".mb": SupportedDCC.MAYA,
    ".nk": SupportedDCC.NUKE,
    ".hip": SupportedDCC.HOUDINI,
    ".hipnc": SupportedDCC.HOUDINI,
    ".blend": SupportedDCC.BLENDER,
    ".max": SupportedDCC.MAX,
}


def validate_dcc(dcc_name: str | SupportedDCC) -> Any:
    """Return the :class:`SupportedDCC` matching ``dcc_name``.

    A :class:`SupportedDCC` instance is returned unchanged which keeps the helper
    ergonomic when the caller already performs validation elsewhere.
    """

    if isinstance(dcc_name, SupportedDCC):
        return dcc_name

    normalized = dcc_name.lower()
    for dcc in SupportedDCC:
        if dcc.value.lower() == normalized:
            return dcc
    supported = ", ".join(sorted(d.value for d in SupportedDCC))
    raise ValueError(f"Unsupported DCC: {dcc_name}. Supported: {supported}")


def detect_dcc_from_file(file_path: str | Path) -> Any:
    """Infer the appropriate :class:`SupportedDCC` from ``file_path``."""

    suffix = Path(file_path).suffix.lower()
    try:
        return _EXTENSION_MAP[suffix]
    except KeyError as exc:
        supported = ", ".join(sorted(_EXTENSION_MAP))
        msg = (
            f"Cannot detect DCC from file extension '{suffix}' (supported: {supported})"
        )
        raise ValueError(msg) from exc
