"""Helpers for generating delivery manifests for OnePiece deliveries."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, MutableMapping

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_JSON_FILENAME = "delivery_manifest.json"
DEFAULT_CSV_FILENAME = "delivery_manifest.csv"

_REQUIRED_FIELDS = (
    "show",
    "episode",
    "scene",
    "shot",
    "asset",
    "version",
    "source_path",
    "delivery_path",
)
_MANIFEST_FIELDS = _REQUIRED_FIELDS + ("checksum",)

__all__ = [
    "compute_checksum",
    "get_manifest_data",
    "write_json_manifest",
    "write_csv_manifest",
    "DEFAULT_JSON_FILENAME",
    "DEFAULT_CSV_FILENAME",
]


def compute_checksum(file_path: str | Path, algorithm: str = "md5", *, chunk_size: int = 65536) -> str:
    """Return the checksum for *file_path* using the requested *algorithm*."""

    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Cannot compute checksum for missing file: {path}")

    algorithm_lower = algorithm.lower()
    if algorithm_lower == "md5":
        hasher = hashlib.md5()
    elif algorithm_lower == "sha256":
        hasher = hashlib.sha256()
    else:  # pragma: no cover - defensive branch
        raise ValueError(f"Unsupported checksum algorithm: {algorithm}")

    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalise_entry(entry: Mapping[str, object], index: int) -> MutableMapping[str, object]:
    missing = [field for field in _REQUIRED_FIELDS if field not in entry]
    if missing:
        raise ValueError(
            "Manifest entry %s is missing required fields: %s" % (index, ", ".join(missing))
        )

    normalised: MutableMapping[str, object] = {}
    for field in _REQUIRED_FIELDS:
        value = entry[field]
        if field == "version":
            try:
                normalised[field] = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                raise ValueError(
                    f"Manifest entry {index} has an invalid version: {value!r}"
                ) from exc
        elif isinstance(value, Path):
            normalised[field] = str(value)
        else:
            normalised[field] = value if isinstance(value, str) else str(value)

    checksum = entry.get("checksum")
    if checksum:
        normalised["checksum"] = checksum if isinstance(checksum, str) else str(checksum)
    else:
        normalised["checksum"] = compute_checksum(normalised["source_path"])  # type: ignore[arg-type]

    return normalised


def _prepare_entries(entries: Iterable[Mapping[str, object]]) -> list[MutableMapping[str, object]]:
    prepared: list[MutableMapping[str, object]] = []
    for index, entry in enumerate(entries):
        prepared.append(_normalise_entry(entry, index))
    return prepared


def get_manifest_data(entries: Iterable[Mapping[str, object]]) -> dict[str, list[MutableMapping[str, object]]]:
    """Return manifest data with checksums ready for serialisation."""

    prepared = _prepare_entries(entries)
    return {"files": prepared}


def _resolve_path(file_path: str | Path | None, default_name: str) -> Path:
    path = Path(file_path) if file_path is not None else Path(default_name)
    _ensure_parent(path)
    return path


def write_json_manifest(
    entries: Iterable[Mapping[str, object]], file_path: str | Path | None = None
) -> Path:
    """Write *entries* to *file_path* (or default JSON manifest) and return the path."""

    manifest_data = get_manifest_data(entries)
    path = _resolve_path(file_path, DEFAULT_JSON_FILENAME)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(manifest_data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    logger.info(
        "json_manifest_written",
        path=str(path),
        file_count=len(manifest_data["files"]),
    )
    return path


def write_csv_manifest(
    entries: Iterable[Mapping[str, object]], file_path: str | Path | None = None
) -> Path:
    """Write *entries* to *file_path* (or default CSV manifest) and return the path."""

    records = _prepare_entries(entries)
    path = _resolve_path(file_path, DEFAULT_CSV_FILENAME)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_MANIFEST_FIELDS))
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    logger.info(
        "csv_manifest_written",
        path=str(path),
        file_count=len(records),
    )
    return path
