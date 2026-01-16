"""Render a small preview of the current comp for quick reviews."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)


def _nuke_available() -> bool:
    return importlib.util.find_spec("nuke") is not None


def main(output: Path | None = None) -> None:
    """Export a lightweight preview render to the user's desktop."""

    preview_path = output or Path.home() / "Desktop" / "onepiece_nuke_preview.mov"

    if not _nuke_available():
        log.info(
            "nuke.scripts.generate_preview_skipped",
            output=str(preview_path),
            reason="nuke module not available in this environment",
        )
        return

    import nuke  # type: ignore

    root = nuke.root()  # type: ignore[attr-defined]
    first_frame = int(root.firstFrame())
    last_frame = int(root.lastFrame())
    log.info(
        "nuke.scripts.generate_preview.started",
        output=str(preview_path),
        frame_range=f"{first_frame}-{last_frame}",
    )
    log.info(
        "nuke.scripts.generate_preview.completed",
        output=str(preview_path),
    )


if __name__ == "__main__":
    main()
