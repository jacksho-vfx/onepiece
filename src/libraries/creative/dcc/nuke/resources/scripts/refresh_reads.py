"""Reload all Read nodes to avoid stale caches before rendering."""

from __future__ import annotations

import importlib.util

import structlog

log = structlog.get_logger(__name__)


def _nuke_available() -> bool:
    return importlib.util.find_spec("nuke") is not None


def main() -> None:
    """Force a reload on every Read node in the current script."""

    if not _nuke_available():
        log.info(
            "nuke.scripts.refresh_reads_skipped",
            reason="nuke module not available in this environment",
        )
        return

    import nuke  # type: ignore

    refreshed = 0
    for node in nuke.allNodes("Read"):  # type: ignore[attr-defined]
        node.reload()  # type: ignore[attr-defined]
        refreshed += 1

    log.info("nuke.scripts.refresh_reads.completed", refreshed=refreshed)


if __name__ == "__main__":
    main()
