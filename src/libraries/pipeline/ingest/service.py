"""Core pipeline ingest workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import hashlib
import mimetypes
import os
import platform
import shutil
import uuid

from libraries.pipeline.ingest.config import IngestConfig
from libraries.pipeline.ingest.deadline import build_deadline_job, submit_deadline_job
from libraries.pipeline.ingest.hooks import (
    IngestContext,
    load_hook_state,
    run_hooks,
    save_hook_state,
)
from libraries.pipeline.ingest.linking import IngestLink, resolve_links
from libraries.pipeline.ingest.metadata import (
    IngestFileRecord,
    IngestMetadata,
    IngestMetadataFile,
    SCHEMA_VERSION,
    now_timestamp,
)


@dataclass(frozen=True)
class IngestResult:
    asset_id: str
    asset_dir: Path
    metadata_path: Path
    links: tuple[IngestLink, ...]


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


def _copy_payload(source: Path, destination: Path) -> Path:
    if source.is_dir():
        target = destination / source.name
        shutil.copytree(source, target)
        return target
    target = destination / source.name
    shutil.copy2(source, target)
    return target


def _collect_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file():
            files.append(path)
    return files


def _build_metadata(
    *,
    asset_id: str,
    source_uri: str,
    payload_root: Path,
    tags: dict[str, list[str]],
    relationships: list[dict[str, str]],
) -> IngestMetadata:
    files: list[IngestFileRecord] = []
    file_types: set[str] = set()
    for file_path in _collect_files(payload_root):
        file_type, mime_type = _classify_file_type(file_path)
        file_types.add(file_type)
        files.append(
            IngestFileRecord(
                path=str(file_path.relative_to(payload_root)),
                size_bytes=file_path.stat().st_size,
                sha256=_hash_file(file_path),
                mime_type=mime_type,
                file_type=file_type,
            )
        )
    return IngestMetadata(
        schema_version=SCHEMA_VERSION,
        asset_id=asset_id,
        source_uri=source_uri,
        ingest_timestamp=now_timestamp(),
        files=tuple(files),
        tags=tags,
        file_types=tuple(sorted(file_types)),
        user={"name": os.getenv("USER") or os.getenv("USERNAME") or "unknown"},
        machine={"hostname": platform.node(), "platform": platform.platform()},
        relationships=relationships,
    )


def _safe_link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination.exists() or destination.is_symlink():
            if destination.is_dir() and not destination.is_symlink():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        os.symlink(source, destination)
    except OSError:
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


def _resolve_conflict(destination: Path, asset_id: str) -> Path:
    if not destination.exists() and not destination.is_symlink():
        return destination
    safe_id = "".join(ch for ch in asset_id if ch.isalnum()) or asset_id
    short_id = safe_id[:8]
    suffix = destination.suffix
    stem = destination.stem
    candidate = destination.with_name(f"{stem}__{short_id}{suffix}")
    if candidate.exists() or candidate.is_symlink():
        return destination.with_name(f"{stem}__{asset_id}{suffix}")
    return candidate


def _link_targets(
    links: tuple[IngestLink, ...],
    asset_id: str,
) -> tuple[IngestLink, ...]:
    created: list[IngestLink] = []
    for link in links:
        destination = _resolve_conflict(link.destination, asset_id)
        _safe_link(link.source, destination)
        created.append(
            IngestLink(
                rule_name=link.rule_name, source=link.source, destination=destination
            )
        )
    return tuple(created)


def _run_deadline_actions(
    *,
    asset_id: str,
    asset_dir: Path,
    payload_root: Path,
    file_types: tuple[str, ...],
    deadline_config: IngestConfig,
) -> None:
    state_path = asset_dir / "deadline.json"
    state = load_hook_state(state_path)
    if "3d_model" not in file_types:
        return
    for action_name, action_config in (
        ("optimize_model", deadline_config.deadline.optimize_model),
        ("convert_to_usd", deadline_config.deadline.convert_to_usd),
    ):
        if not action_config.enabled:
            continue
        if action_name in state:
            continue
        job = build_deadline_job(
            action=action_name,
            asset_id=asset_id,
            asset_dir=asset_dir,
            payload_path=payload_root,
            config=action_config,
        )
        submission_output = submit_deadline_job(job)
        state[action_name] = submission_output or now_timestamp()
        save_hook_state(state_path, state)


def ingest_asset(
    *,
    source: Path,
    project_root: Path,
    config: IngestConfig,
    asset_id: str | None = None,
    tags: list[str] | None = None,
    controlled_tags: list[str] | None = None,
    relationships: list[dict[str, str]] | None = None,
) -> IngestResult:
    source = source.expanduser().resolve()
    project_root = project_root.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source path not found: {source}")
    ingest_root = project_root / ".pipeline" / "ingest"
    ingest_root.mkdir(parents=True, exist_ok=True)
    asset_id = asset_id or uuid.uuid4().hex
    asset_dir = ingest_root / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)
    payload_root = _copy_payload(source, asset_dir)

    metadata = _build_metadata(
        asset_id=asset_id,
        source_uri=source.as_posix(),
        payload_root=payload_root,
        tags={
            "freeform": sorted(set(tags or [])),
            "controlled": sorted(set(controlled_tags or [])),
        },
        relationships=relationships or [],
    )
    metadata_file = IngestMetadataFile(asset_dir / "metadata.json")
    metadata_file.write(metadata)

    payload_extensions = {path.suffix.lower() for path in _collect_files(payload_root)}
    links = resolve_links(
        rules=config.link_rules,
        metadata=metadata,
        project_root=project_root,
        payload=payload_root if payload_root.is_dir() else payload_root,
        payload_basename=payload_root.name,
        payload_extensions=payload_extensions,
    )
    created_links = _link_targets(links, asset_id)

    context = IngestContext(
        asset_id=asset_id,
        asset_dir=asset_dir,
        metadata_path=metadata_file.path,
        project_root=project_root,
    )
    hook_configs = [hook for hook in config.hooks if hook.enabled]
    run_hooks(
        context, [{"name": hook.name, "config": hook.config} for hook in hook_configs]
    )
    _run_deadline_actions(
        asset_id=asset_id,
        asset_dir=asset_dir,
        payload_root=payload_root,
        file_types=metadata.file_types,
        deadline_config=config,
    )

    return IngestResult(
        asset_id=asset_id,
        asset_dir=asset_dir,
        metadata_path=metadata_file.path,
        links=created_links,
    )
