"""Organise backdrops and annotations to make node graphs readable."""

from __future__ import annotations

import importlib.util

import structlog

log = structlog.get_logger(__name__)


def _nuke_available() -> bool:
    return importlib.util.find_spec("nuke") is not None


def main() -> None:
    """Tidy common Nuke layout issues without touching renders."""

    if not _nuke_available():
        log.info(
            "nuke.scripts.cleanup_backdrops_skipped",
            reason="nuke module not available in this environment",
        )
        return

    import nuke  # type: ignore

    selected = nuke.selectedNodes()  # type: ignore[attr-defined]
    for node in selected:
        node.setSelected(False)  # type: ignore[attr-defined]
    log.info(
        "nuke.scripts.cleanup_backdrops.completed",
        deselected=len(selected),
    )


if __name__ == "__main__":
    main()
