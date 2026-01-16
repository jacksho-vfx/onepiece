"""Local inventory index for pipeline ingest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from libraries.pipeline.ingest.metadata import IngestMetadataFile


@dataclass(frozen=True)
class AssetIndexEntry:
    asset_id: str
    payload_name: str
    payload_hash: str
    payload_size_bytes: int
    tags: list[str]
    file_types: list[str]


@dataclass(frozen=True)
class AssetIndexRecord(AssetIndexEntry):
    source_uri: str
    links: list[dict[str, str]]


def _index_root(project_root: Path) -> Path:
    return project_root / ".pipeline" / "index"


def _index_manifest_path(project_root: Path) -> Path:
    return _index_root(project_root) / "index.json"


def _asset_index_path(project_root: Path, asset_id: str) -> Path:
    return _index_root(project_root) / "assets" / f"{asset_id}.json"


def _ensure_index_dirs(project_root: Path) -> None:
    root = _index_root(project_root)
    (root / "assets").mkdir(parents=True, exist_ok=True)


def _load_index_manifest(project_root: Path) -> dict[str, Any]:
    path = _index_manifest_path(project_root)
    if not path.exists():
        return {"assets": []}
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        return {"assets": []}
    return payload


def _write_index_manifest(project_root: Path, payload: dict[str, Any]) -> None:
    _ensure_index_dirs(project_root)
    _index_manifest_path(project_root).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )


def write_asset_record(project_root: Path, record: AssetIndexRecord) -> None:
    _ensure_index_dirs(project_root)
    payload = {
        "asset_id": record.asset_id,
        "payload_name": record.payload_name,
        "payload_hash": record.payload_hash,
        "payload_size_bytes": record.payload_size_bytes,
        "tags": record.tags,
        "file_types": record.file_types,
        "source_uri": record.source_uri,
        "links": record.links,
    }
    _asset_index_path(project_root, record.asset_id).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )

    manifest = _load_index_manifest(project_root)
    assets = [item for item in manifest.get("assets", []) if isinstance(item, dict)]
    assets = [item for item in assets if item.get("asset_id") != record.asset_id]
    assets.append(
        {
            "asset_id": record.asset_id,
            "payload_name": record.payload_name,
            "payload_hash": record.payload_hash,
            "payload_size_bytes": record.payload_size_bytes,
            "tags": record.tags,
            "file_types": record.file_types,
        }
    )
    manifest["assets"] = sorted(assets, key=lambda item: str(item.get("asset_id")))
    _write_index_manifest(project_root, manifest)


def load_asset_record(project_root: Path, asset_id: str) -> AssetIndexRecord:
    payload = json.loads(_asset_index_path(project_root, asset_id).read_text())
    return AssetIndexRecord(
        asset_id=str(payload.get("asset_id", asset_id)),
        payload_name=str(payload.get("payload_name", "")),
        payload_hash=str(payload.get("payload_hash", "")),
        payload_size_bytes=int(payload.get("payload_size_bytes", 0)),
        tags=list(payload.get("tags", []) or []),
        file_types=list(payload.get("file_types", []) or []),
        source_uri=str(payload.get("source_uri", "")),
        links=list(payload.get("links", []) or []),
    )


def search_by_tag(project_root: Path, tag: str) -> list[AssetIndexEntry]:
    manifest = _load_index_manifest(project_root)
    assets = []
    for item in manifest.get("assets", []):
        if not isinstance(item, dict):
            continue
        tags = set(item.get("tags", []) or [])
        if tag not in tags:
            continue
        assets.append(
            AssetIndexEntry(
                asset_id=str(item.get("asset_id", "")),
                payload_name=str(item.get("payload_name", "")),
                payload_hash=str(item.get("payload_hash", "")),
                payload_size_bytes=int(item.get("payload_size_bytes", 0)),
                tags=list(tags),
                file_types=list(item.get("file_types", []) or []),
            )
        )
    return assets


def search_by_name(project_root: Path, query: str) -> list[AssetIndexEntry]:
    manifest = _load_index_manifest(project_root)
    query_lower = query.lower()
    assets = []
    for item in manifest.get("assets", []):
        if not isinstance(item, dict):
            continue
        payload_name = str(item.get("payload_name", ""))
        if query_lower not in payload_name.lower():
            continue
        assets.append(
            AssetIndexEntry(
                asset_id=str(item.get("asset_id", "")),
                payload_name=payload_name,
                payload_hash=str(item.get("payload_hash", "")),
                payload_size_bytes=int(item.get("payload_size_bytes", 0)),
                tags=list(item.get("tags", []) or []),
                file_types=list(item.get("file_types", []) or []),
            )
        )
    return assets


def rebuild_index(project_root: Path) -> None:
    ingest_root = project_root / ".pipeline" / "ingest"
    if not ingest_root.exists():
        _write_index_manifest(project_root, {"assets": []})
        return
    _ensure_index_dirs(project_root)
    manifest: dict[str, Any] = {"assets": []}
    for metadata_path in ingest_root.glob("*/metadata.json"):
        metadata = IngestMetadataFile(metadata_path).read()
        links_path = metadata_path.parent / "links.json"
        links: list[dict[str, str]] = []
        if links_path.exists():
            payload = json.loads(links_path.read_text())
            if isinstance(payload, list):
                links = [
                    {
                        "source": str(item.get("source", "")),
                        "destination": str(item.get("destination", "")),
                    }
                    for item in payload
                    if isinstance(item, dict)
                ]
        record = AssetIndexRecord(
            asset_id=metadata.asset_id,
            payload_name=metadata.payload_name,
            payload_hash=metadata.payload_hash,
            payload_size_bytes=metadata.payload_size_bytes,
            tags=sorted(
                set(
                    metadata.tags.get("freeform", [])
                    + metadata.tags.get("controlled", [])
                )
            ),
            file_types=list(metadata.file_types),
            source_uri=metadata.source_uri,
            links=links,
        )
        write_asset_record(project_root, record)
        manifest["assets"].append(
            {
                "asset_id": record.asset_id,
                "payload_name": record.payload_name,
                "payload_hash": record.payload_hash,
                "payload_size_bytes": record.payload_size_bytes,
                "tags": record.tags,
                "file_types": record.file_types,
            }
        )
    manifest["assets"] = sorted(manifest["assets"], key=lambda item: item["asset_id"])
    _write_index_manifest(project_root, manifest)
