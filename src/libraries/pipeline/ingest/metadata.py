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


@dataclass(frozen=True)
class IngestMetadataFile:
    path: Path

    def write(self, metadata: IngestMetadata) -> None:
        self.path.write_text(_format_json(metadata.to_dict()))


SCHEMA_VERSION = "1.0"


def now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
