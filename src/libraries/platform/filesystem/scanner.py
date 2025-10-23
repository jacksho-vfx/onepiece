"""Utilities to inspect project files on the filesystem."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import structlog

from libraries.automation.reconcile.parsing import extract_from_path

log = structlog.get_logger(__name__)


def scan_project_files(
    project_root: Path | str, scope: str = "shots"
) -> List[Dict[str, str]]:
    """Return files found under *project_root* with parsed metadata.

    Each returned dictionary contains ``shot`` (or asset name), ``version``, and
    the absolute ``path`` to the file on disk. Entries that do not conform to the
    naming conventions are skipped.
    """

    normalised_scope = scope.lower()

    root = Path(project_root)
    if not root.exists():
        log.warning("filesystem.scan.missing_root", root=str(root))
        return []

    results: List[Dict[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        entity, version = extract_from_path(path, scope=normalised_scope)
        if not entity or not version:
            continue
        results.append({"shot": entity, "version": version, "path": str(path)})

    log.info(
        "filesystem.scan.complete",
        root=str(root),
        scope=normalised_scope,
        files=len(results),
    )
    results.sort(key=lambda item: (item["shot"], item["version"], item["path"]))
    return results
