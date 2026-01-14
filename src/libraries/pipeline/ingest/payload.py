"""Payload inspection helpers for pipeline ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import hashlib
import mimetypes

from libraries.pipeline.ingest.metadata import IngestFileRecord


_FILE_TYPE_MAP: dict[str, str] = {
    ".fbx": "3d_model",
    ".obj": "3d_model",
    ".usd": "3d_model",
    ".usda": "3d_model",
    ".usdc": "3d_model",
    ".abc": "3d_model",
    ".gltf": "3d_model",
    ".glb": "3d_model",
    ".exr": "image",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".mov": "video",
    ".mp4": "video",
}


@dataclass(frozen=True)
class PayloadManifest:
    payload_name: str
    payload_hash: str
    payload_size_bytes: int
    files: tuple[IngestFileRecord, ...]
    file_types: tuple[str, ...]
    extensions: set[str]


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _classify_file_type(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    file_type = _FILE_TYPE_MAP.get(ext, "unknown")
    mime_type, _ = mimetypes.guess_type(path.as_posix())
    return file_type, mime_type or "application/octet-stream"


def _collect_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file():
            files.append(path)
    return files


def _build_payload_hash(records: list[IngestFileRecord]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item.path):
        digest.update(record.path.encode("utf-8"))
        digest.update(str(record.size_bytes).encode("utf-8"))
        digest.update(record.sha256.encode("utf-8"))
    return digest.hexdigest()


def build_payload_manifest(source: Path) -> PayloadManifest:
    source = source.expanduser().resolve()
    files: list[IngestFileRecord] = []
    file_types: set[str] = set()
    extensions: set[str] = set()
    total_size = 0
    for file_path in _collect_files(source):
        file_type, mime_type = _classify_file_type(file_path)
        file_types.add(file_type)
        extensions.add(file_path.suffix.lower())
        size_bytes = file_path.stat().st_size
        total_size += size_bytes
        files.append(
            IngestFileRecord(
                path=str(file_path.relative_to(source)),
                size_bytes=size_bytes,
                sha256=_hash_file(file_path),
                mime_type=mime_type,
                file_type=file_type,
            )
        )
    payload_hash = _build_payload_hash(files)
    return PayloadManifest(
        payload_name=source.name,
        payload_hash=payload_hash,
        payload_size_bytes=total_size,
        files=tuple(files),
        file_types=tuple(sorted(file_types)),
        extensions=extensions,
    )
