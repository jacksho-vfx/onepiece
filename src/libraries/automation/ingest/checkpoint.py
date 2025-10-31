"""Checkpointing helpers and uploader protocols for the ingest workflow."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .logging_utils import get_logger


log = get_logger(__name__)


class UploaderProtocol(Protocol):
    """Protocol describing the minimal interface required for uploads."""

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        """Upload *file_path* to ``s3://bucket/key``."""


@dataclass
class UploadCheckpoint:
    """Persisted state describing progress for a resumable upload."""

    file_path: Path
    bucket: str
    key: str
    file_size: int
    bytes_transferred: int = 0
    parts: list[tuple[int, str]] = field(default_factory=list)
    upload_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "file_path": str(self.file_path),
            "bucket": self.bucket,
            "key": self.key,
            "file_size": self.file_size,
            "bytes_transferred": self.bytes_transferred,
            "parts": [[part, etag] for part, etag in self.parts],
            "upload_id": self.upload_id,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "UploadCheckpoint":
        parts_payload = payload.get("parts", [])
        parts: list[tuple[int, str]] = []
        for entry in parts_payload:
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                part_number = int(entry[0])
                etag = str(entry[1])
                parts.append((part_number, etag))
        return cls(
            file_path=Path(str(payload["file_path"])),
            bucket=str(payload["bucket"]),
            key=str(payload["key"]),
            file_size=int(payload.get("file_size", 0)),
            bytes_transferred=int(payload.get("bytes_transferred", 0)),
            parts=parts,
            upload_id=payload.get("upload_id"),
        )


@runtime_checkable
class ResumableUploaderProtocol(UploaderProtocol, Protocol):
    """Uploader that supports resumable, checkpointed transfers."""

    def upload_resumable(
        self,
        file_path: Path,
        bucket: str,
        key: str,
        checkpoint: UploadCheckpoint,
        chunk_size: int,
        progress_callback: Callable[[UploadCheckpoint], None] | None = None,
    ) -> None:
        """Upload using *checkpoint* state and invoke *progress_callback* per chunk."""


@runtime_checkable
class ObjectInspectorProtocol(Protocol):
    """Uploader that can inspect remote S3 object metadata."""

    def head_object(self, bucket: str, key: str) -> Mapping[str, Any]:
        """Return metadata describing ``s3://bucket/key`` if it exists."""


class UploadCheckpointStore:
    """Thread-safe persistence helper for resumable upload checkpoints."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._lock = threading.Lock()
        self._directory.mkdir(parents=True, exist_ok=True)

    def load(self, bucket: str, key: str) -> UploadCheckpoint | None:
        path = self._entry_path(bucket, key)
        with self._lock:
            if not path.exists():
                return None
            raw = path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("ingest.checkpoint_corrupt", checkpoint=str(path))
            return None
        try:
            return UploadCheckpoint.from_payload(payload)
        except (KeyError, TypeError, ValueError) as exc:
            log.warning(
                "ingest.checkpoint_invalid",
                checkpoint=str(path),
                error=str(exc),
            )
            return None

    def save(self, checkpoint: UploadCheckpoint) -> None:
        path = self._entry_path(checkpoint.bucket, checkpoint.key)
        payload = checkpoint.to_payload()
        encoded = json.dumps(payload, indent=2, sort_keys=True)
        temp_path = path.with_suffix(".tmp")
        with self._lock:
            temp_path.write_text(encoded, encoding="utf-8")
            temp_path.replace(path)

    def delete(self, bucket: str, key: str) -> None:
        path = self._entry_path(bucket, key)
        with self._lock:
            if path.exists():
                path.unlink()

    def _entry_path(self, bucket: str, key: str) -> Path:
        digest = hashlib.sha1(f"{bucket}:{key}".encode("utf-8")).hexdigest()
        return self._directory / f"{digest}.json"


__all__ = [
    "UploaderProtocol",
    "UploadCheckpoint",
    "ResumableUploaderProtocol",
    "ObjectInspectorProtocol",
    "UploadCheckpointStore",
]
