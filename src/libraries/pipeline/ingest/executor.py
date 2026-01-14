"""Resumable ingest execution for queued items."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import os
import shutil
import uuid

from libraries.pipeline.ingest.config import IngestConfig, load_ingest_config
from libraries.pipeline.ingest.deadline import build_deadline_job, submit_deadline_job
from libraries.pipeline.ingest.hooks import (
    IngestContext,
    load_hook_state,
    run_hooks,
    save_hook_state,
)
from libraries.pipeline.ingest.inventory import AssetIndexRecord, write_asset_record
from libraries.pipeline.ingest.metadata import (
    IngestMetadata,
    IngestMetadataFile,
    now_timestamp,
)
from libraries.pipeline.ingest.payload import build_payload_manifest
from libraries.pipeline.ingest.queue import IngestQueueItem
from libraries.pipeline.ingest.rules import (
    IngestRuleSet,
    PlannedLink,
    build_link_destination,
    load_ingest_rules,
    plan_ingest,
)
from libraries.pipeline.ingest.tagging import infer_tags


@dataclass(frozen=True)
class IngestExecutionResult:
    asset_id: str
    asset_dir: Path
    metadata_path: Path
    links: tuple[PlannedLink, ...]
    hooks: tuple[str, ...]
    deadline_actions: tuple[str, ...]


PROGRESS_COPY = "COPY_DONE"
PROGRESS_META = "META_DONE"
PROGRESS_LINK = "LINK_DONE"
PROGRESS_HOOKS = "HOOKS_DONE"
PROGRESS_DEADLINE = "DEADLINE_DONE"
PROGRESS_INDEX = "INDEX_DONE"


def _progress_path(asset_dir: Path) -> Path:
    return asset_dir / "progress.json"


def load_progress(asset_dir: Path) -> dict[str, str]:
    path = _progress_path(asset_dir)
    if not path.exists():
        return {}
    import json

    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        return {}
    return {str(key): str(value) for key, value in payload.items()}


def save_progress(asset_dir: Path, progress: dict[str, str]) -> None:
    import json

    _progress_path(asset_dir).write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n"
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


def _copy_payload(source: Path, destination: Path) -> Path:
    if source.is_dir():
        target = destination / source.name
        shutil.copytree(source, target)
        return target
    target = destination / source.name
    shutil.copy2(source, target)
    return target


def _remove_payload(target: Path) -> None:
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    elif target.exists() or target.is_symlink():
        target.unlink()


def _merge_metadata(
    *,
    existing: IngestMetadata | None,
    updated: IngestMetadata,
    force: bool,
) -> IngestMetadata:
    if existing is None or force:
        return updated
    return IngestMetadata(
        schema_version=existing.schema_version,
        asset_id=existing.asset_id,
        source_uri=updated.source_uri or existing.source_uri,
        ingest_timestamp=existing.ingest_timestamp,
        payload_name=existing.payload_name,
        payload_hash=existing.payload_hash,
        payload_size_bytes=existing.payload_size_bytes,
        files=existing.files,
        tags=updated.tags,
        file_types=existing.file_types,
        user=existing.user,
        machine=existing.machine,
        relationships=updated.relationships,
    )


def _load_ingest_config(project_root: Path, item: IngestQueueItem) -> IngestConfig:
    if item.config_path:
        return load_ingest_config(Path(item.config_path))
    default_path = project_root / ".pipeline" / "ingest_config.yaml"
    if default_path.exists():
        return load_ingest_config(default_path)
    return IngestConfig()


def _load_rules(project_root: Path, item: IngestQueueItem) -> IngestRuleSet:
    if item.rules_path:
        return load_ingest_rules(Path(item.rules_path))
    default_path = project_root / ".pipeline" / "ingest_rules.yaml"
    if default_path.exists():
        return load_ingest_rules(default_path)
    raise ValueError(
        "No ingest rules found. Provide --rules or add .pipeline/ingest_rules.yaml"
    )


def _write_links(asset_dir: Path, links: list[dict[str, str]]) -> None:
    import json

    (asset_dir / "links.json").write_text(
        json.dumps(links, indent=2, sort_keys=True) + "\n"
    )


def _execute_deadline_actions(
    *,
    asset_id: str,
    asset_dir: Path,
    payload_root: Path,
    file_types: tuple[str, ...],
    deadline_config: IngestConfig,
    actions: tuple[str, ...],
) -> None:
    state_path = asset_dir / "deadline.json"
    state = load_hook_state(state_path)
    if "3d_model" not in file_types:
        return
    actions_map = {
        "optimize_model": deadline_config.deadline.optimize_model,
        "convert_to_usd": deadline_config.deadline.convert_to_usd,
    }
    for action_name in actions:
        action_config = actions_map.get(action_name)
        if action_config is None or not action_config.enabled:
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
        state[action_name] = submission_output or "submitted"
        save_hook_state(state_path, state)


def execute_queue_item(
    *,
    item: IngestQueueItem,
    project_root: Path,
    resume: bool,
    force: bool,
) -> IngestExecutionResult:
    source = Path(item.source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source path not found: {source}")

    ingest_root = project_root / ".pipeline" / "ingest"
    ingest_root.mkdir(parents=True, exist_ok=True)
    asset_id = item.asset_id or uuid.uuid4().hex
    item.asset_id = asset_id
    asset_dir = ingest_root / asset_id
    asset_dir.mkdir(parents=True, exist_ok=True)

    progress = load_progress(asset_dir)
    payload_target = asset_dir / source.name
    source_manifest = build_payload_manifest(source)

    if not force and resume and PROGRESS_COPY in progress:
        pass
    else:
        should_copy = True
        if payload_target.exists():
            metadata_path = asset_dir / "metadata.json"
            if metadata_path.exists():
                existing_metadata = IngestMetadataFile(metadata_path).read()
                if existing_metadata.payload_hash == source_manifest.payload_hash:
                    should_copy = False
            if should_copy:
                try:
                    existing_manifest = build_payload_manifest(payload_target)
                except FileNotFoundError:
                    existing_manifest = None
                if (
                    existing_manifest
                    and existing_manifest.payload_hash == source_manifest.payload_hash
                ):
                    should_copy = False
        if should_copy:
            if payload_target.exists() or payload_target.is_symlink():
                _remove_payload(payload_target)
            _copy_payload(source, asset_dir)
        progress[PROGRESS_COPY] = "done"
        save_progress(asset_dir, progress)

    payload_manifest = build_payload_manifest(payload_target)

    tags = infer_tags(
        source,
        manifest=source_manifest,
        user_tags=item.tags,
        controlled_tags=item.controlled_tags,
    )

    metadata_file = IngestMetadataFile(asset_dir / "metadata.json")
    existing_metadata = metadata_file.read() if metadata_file.path.exists() else None
    updated_metadata = IngestMetadata(
        schema_version=existing_metadata.schema_version if existing_metadata else "1.1",
        asset_id=asset_id,
        source_uri=source.as_posix(),
        ingest_timestamp=(
            existing_metadata.ingest_timestamp if existing_metadata else now_timestamp()
        ),
        payload_name=payload_manifest.payload_name,
        payload_hash=payload_manifest.payload_hash,
        payload_size_bytes=payload_manifest.payload_size_bytes,
        files=payload_manifest.files,
        tags=tags,
        file_types=payload_manifest.file_types,
        user=(
            existing_metadata.user
            if existing_metadata
            else {"name": os.getenv("USER") or "unknown"}
        ),
        machine=existing_metadata.machine if existing_metadata else {},
        relationships=existing_metadata.relationships if existing_metadata else [],
    )
    if not (resume and PROGRESS_META in progress) or force:
        merged = _merge_metadata(
            existing=existing_metadata, updated=updated_metadata, force=force
        )
        metadata_file.write(merged)
        progress[PROGRESS_META] = "done"
        save_progress(asset_dir, progress)

    rules = _load_rules(project_root, item)
    tag_set = set(tags.get("freeform", [])) | set(tags.get("controlled", []))
    plan = plan_ingest(
        rules=rules,
        tags=tag_set,
        file_types=set(source_manifest.file_types),
        extensions=source_manifest.extensions,
        source_path=source.as_posix().lower(),
        payload_size_bytes=source_manifest.payload_size_bytes,
    )

    created_links: list[dict[str, str]] = []
    if not (resume and PROGRESS_LINK in progress) or force:
        for link in plan.links:
            destination = build_link_destination(
                output=link.output,
                project_root=project_root,
                asset_id=asset_id,
                basename=payload_manifest.payload_name,
                source_uri=source.as_posix(),
                payload_name=payload_manifest.payload_name,
            )
            destination = _resolve_conflict(destination, asset_id)
            _safe_link(payload_target, destination)
            created_links.append(
                {
                    "rule_name": link.rule_name,
                    "source": payload_target.as_posix(),
                    "destination": destination.as_posix(),
                }
            )
        _write_links(asset_dir, created_links)
        progress[PROGRESS_LINK] = "done"
        save_progress(asset_dir, progress)
    elif (asset_dir / "links.json").exists():
        import json

        payload = json.loads((asset_dir / "links.json").read_text())
        if isinstance(payload, list):
            created_links = [
                {
                    "rule_name": str(item.get("rule_name", "")),
                    "source": str(item.get("source", "")),
                    "destination": str(item.get("destination", "")),
                }
                for item in payload
                if isinstance(item, dict)
            ]

    ingest_config = _load_ingest_config(project_root, item)
    if not (resume and PROGRESS_HOOKS in progress) or force:
        context = IngestContext(
            asset_id=asset_id,
            asset_dir=asset_dir,
            metadata_path=metadata_file.path,
            project_root=project_root,
        )
        hook_configs = [
            hook
            for hook in ingest_config.hooks
            if hook.enabled and hook.name in plan.hooks
        ]
        run_hooks(
            context,
            [{"name": hook.name, "config": hook.config} for hook in hook_configs],
        )
        progress[PROGRESS_HOOKS] = "done"
        save_progress(asset_dir, progress)

    if not (resume and PROGRESS_DEADLINE in progress) or force:
        _execute_deadline_actions(
            asset_id=asset_id,
            asset_dir=asset_dir,
            payload_root=payload_target,
            file_types=payload_manifest.file_types,
            deadline_config=ingest_config,
            actions=plan.deadline_actions,
        )
        progress[PROGRESS_DEADLINE] = "done"
        save_progress(asset_dir, progress)

    if not (resume and PROGRESS_INDEX in progress) or force:
        record = AssetIndexRecord(
            asset_id=asset_id,
            payload_name=payload_manifest.payload_name,
            payload_hash=payload_manifest.payload_hash,
            payload_size_bytes=payload_manifest.payload_size_bytes,
            tags=sorted(tag_set),
            file_types=list(payload_manifest.file_types),
            source_uri=source.as_posix(),
            links=created_links,
        )
        write_asset_record(project_root, record)
        progress[PROGRESS_INDEX] = "done"
        save_progress(asset_dir, progress)

    return IngestExecutionResult(
        asset_id=asset_id,
        asset_dir=asset_dir,
        metadata_path=metadata_file.path,
        links=plan.links,
        hooks=plan.hooks,
        deadline_actions=plan.deadline_actions,
    )
