"""Helpers for generating delivery manifests."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

__all__ = ["calculate_checksum", "write_json_manifest", "write_csv_manifest"]


def calculate_checksum(path: Path, *, chunk_size: int = 65536) -> str:
    """Return the MD5 checksum of *path*."""

    hasher = hashlib.md5()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json_manifest(records: Sequence[Mapping[str, object]], path: Path) -> None:
    """Write *records* to *path* in JSON format."""

    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(list(records), handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_csv_manifest(records: Sequence[Mapping[str, object]], path: Path) -> None:
    """Write *records* to *path* as CSV."""

    _ensure_parent(path)
    fieldnames: list[str] = []
    if records:
        fieldnames = list(records[0].keys())
    else:
        fieldnames = [
            "show",
            "episode",
            "scene",
            "shot",
            "asset",
            "version",
            "source_path",
            "delivery_path",
            "status",
            "checksum",
        ]

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(dict(record))
