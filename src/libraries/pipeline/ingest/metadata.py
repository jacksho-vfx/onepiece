"""Metadata generation for pipeline ingest."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IngestFileRecord:
    path: str
    size_bytes: int
    sha256: str
    mime_type: str
    file_type: str


@dataclass(frozen=True)
class IngestMetadata:
    schema_version: str
    asset_id: str
    source_uri: str
    ingest_timestamp: str
    payload_name: str
    payload_hash: str
    payload_size_bytes: int
    files: tuple[IngestFileRecord, ...]
    tags: dict[str, list[str]]
    file_types: tuple[str, ...]
    user: dict[str, str]
    machine: dict[str, str]
    relationships: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "source_uri": self.source_uri,
            "ingest_timestamp": self.ingest_timestamp,
            "payload_name": self.payload_name,
            "payload_hash": self.payload_hash,
            "payload_size_bytes": self.payload_size_bytes,
            "files": [
                {
                    "path": file.path,
                    "size_bytes": file.size_bytes,
                    "sha256": file.sha256,
                    "mime_type": file.mime_type,
                    "file_type": file.file_type,
                }
                for file in self.files
            ],
            "tags": self.tags,
            "file_types": list(self.file_types),
            "user": self.user,
            "machine": self.machine,
            "relationships": self.relationships,
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "IngestMetadata":
        files = tuple(
            IngestFileRecord(
                path=str(item.get("path", "")),
                size_bytes=int(item.get("size_bytes", 0)),
                sha256=str(item.get("sha256", "")),
                mime_type=str(item.get("mime_type", "")),
                file_type=str(item.get("file_type", "")),
            )
            for item in payload.get("files", [])
            if isinstance(item, dict)
        )
        return IngestMetadata(
            schema_version=str(payload.get("schema_version", "1.0")),
            asset_id=str(payload.get("asset_id", "")),
            source_uri=str(payload.get("source_uri", "")),
            ingest_timestamp=str(payload.get("ingest_timestamp", "")),
            payload_name=str(payload.get("payload_name", "")),
            payload_hash=str(payload.get("payload_hash", "")),
            payload_size_bytes=int(payload.get("payload_size_bytes", 0)),
            files=files,
            tags=(
                dict(payload.get("tags", {}))
                if isinstance(payload.get("tags"), dict)
                else {}
            ),
            file_types=tuple(payload.get("file_types", []) or ()),
            user=(
                dict(payload.get("user", {}))
                if isinstance(payload.get("user"), dict)
                else {}
            ),
            machine=(
                dict(payload.get("machine", {}))
                if isinstance(payload.get("machine"), dict)
                else {}
            ),
            relationships=list(payload.get("relationships", []) or []),
        )


@dataclass(frozen=True)
class IngestMetadataFile:
    path: Path

    def write(self, metadata: IngestMetadata) -> None:
        self.path.write_text(_format_json(metadata.to_dict()))

    def read(self) -> IngestMetadata:
        import json

        payload = json.loads(self.path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("Metadata payload must be a JSON object")
        return IngestMetadata.from_dict(payload)


SCHEMA_VERSION = "1.1"


def now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
