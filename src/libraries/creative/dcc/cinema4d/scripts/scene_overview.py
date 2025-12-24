"""Print a lightweight summary of the currently active Cinema 4D document."""

from __future__ import annotations

from typing import cast


def _safe_imports() -> object | None:
    try:  # pragma: no cover - runtime depends on Cinema 4D
        import c4d  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - fallback for tests
        return None
    return cast(object, c4d)


def main() -> None:
    """Report the name of the active document and its frames-per-second."""

    c4d = _safe_imports()
    if c4d is None:
        print("Cinema 4D API is unavailable; run inside the host to inspect scenes.")
        return

    doc = None
    if hasattr(c4d, "documents"):
        get_active = getattr(c4d.documents, "GetActiveDocument", None)
        doc = get_active() if callable(get_active) else None

    name = None
    if doc is not None:
        get_name = getattr(doc, "GetDocumentName", None)
        name = get_name() if callable(get_name) else None

    fps = None
    if doc is not None:
        get_fps = getattr(doc, "GetFps", None)
        fps = get_fps() if callable(get_fps) else None

    print(f"Active document: {name or 'Unknown'}")
    if fps:
        print(f"Frame rate: {fps} fps")


if __name__ == "__main__":  # pragma: no cover - exercised inside DCC
    main()
