"""Queue persistence for pipeline ingest sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import json
import uuid

from libraries.pipeline.ingest.metadata import now_timestamp


@dataclass
class IngestSession:
    session_id: str
    created_at: str
    user: str
    host: str
    project_root: str
    status: str
    item_ids: list[str] = field(default_factory=list)


@dataclass
class IngestQueueItem:
    item_id: str
    session_id: str
    source: str
    status: str
    created_at: str
    tags: list[str] = field(default_factory=list)
    controlled_tags: list[str] = field(default_factory=list)
    rules_path: str | None = None
    config_path: str | None = None
    asset_id: str | None = None
    progress: dict[str, str] = field(default_factory=dict)
    error: str | None = None


SESSION_STATUSES = {"queued", "running", "completed", "failed", "cancelled"}
ITEM_STATUSES = {
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
    "skipped",
}


def _queue_root(project_root: Path) -> Path:
    return project_root / ".pipeline" / "queue"


def _session_path(project_root: Path, session_id: str) -> Path:
    return _queue_root(project_root) / "sessions" / f"{session_id}.json"


def _item_path(project_root: Path, item_id: str) -> Path:
    return _queue_root(project_root) / "items" / f"{item_id}.json"


def _ensure_queue_dirs(project_root: Path) -> None:
    root = _queue_root(project_root)
    (root / "sessions").mkdir(parents=True, exist_ok=True)
    (root / "items").mkdir(parents=True, exist_ok=True)


def create_session(
    *,
    project_root: Path,
    user: str,
    host: str,
    status: str = "queued",
) -> IngestSession:
    _ensure_queue_dirs(project_root)
    session = IngestSession(
        session_id=uuid.uuid4().hex,
        created_at=now_timestamp(),
        user=user,
        host=host,
        project_root=project_root.as_posix(),
        status=status,
    )
    save_session(project_root, session)
    return session


def load_session(project_root: Path, session_id: str) -> IngestSession:
    data = json.loads(_session_path(project_root, session_id).read_text())
    if not isinstance(data, dict):
        raise ValueError("Session payload must be a JSON object")
    return IngestSession(
        session_id=str(data.get("session_id", session_id)),
        created_at=str(data.get("created_at", "")),
        user=str(data.get("user", "")),
        host=str(data.get("host", "")),
        project_root=str(data.get("project_root", project_root)),
        status=str(data.get("status", "queued")),
        item_ids=list(data.get("item_ids", []) or []),
    )


def save_session(project_root: Path, session: IngestSession) -> None:
    _ensure_queue_dirs(project_root)
    payload = {
        "session_id": session.session_id,
        "created_at": session.created_at,
        "user": session.user,
        "host": session.host,
        "project_root": session.project_root,
        "status": session.status,
        "item_ids": session.item_ids,
    }
    _session_path(project_root, session.session_id).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )


def add_queue_item(
    *,
    project_root: Path,
    session: IngestSession,
    source: Path,
    tags: Iterable[str],
    controlled_tags: Iterable[str],
    rules_path: Path | None,
    config_path: Path | None,
) -> IngestQueueItem:
    _ensure_queue_dirs(project_root)
    item = IngestQueueItem(
        item_id=uuid.uuid4().hex,
        session_id=session.session_id,
        source=source.as_posix(),
        status="queued",
        created_at=now_timestamp(),
        tags=list(tags),
        controlled_tags=list(controlled_tags),
        rules_path=rules_path.as_posix() if rules_path else None,
        config_path=config_path.as_posix() if config_path else None,
    )
    save_queue_item(project_root, item)
    session.item_ids.append(item.item_id)
    save_session(project_root, session)
    return item


def save_queue_item(project_root: Path, item: IngestQueueItem) -> None:
    _ensure_queue_dirs(project_root)
    payload = {
        "item_id": item.item_id,
        "session_id": item.session_id,
        "source": item.source,
        "status": item.status,
        "created_at": item.created_at,
        "tags": item.tags,
        "controlled_tags": item.controlled_tags,
        "rules_path": item.rules_path,
        "config_path": item.config_path,
        "asset_id": item.asset_id,
        "progress": item.progress,
        "error": item.error,
    }
    _item_path(project_root, item.item_id).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )


def load_queue_item(project_root: Path, item_id: str) -> IngestQueueItem:
    data = json.loads(_item_path(project_root, item_id).read_text())
    if not isinstance(data, dict):
        raise ValueError("Queue item payload must be a JSON object")
    return IngestQueueItem(
        item_id=str(data.get("item_id", item_id)),
        session_id=str(data.get("session_id", "")),
        source=str(data.get("source", "")),
        status=str(data.get("status", "queued")),
        created_at=str(data.get("created_at", "")),
        tags=list(data.get("tags", []) or []),
        controlled_tags=list(data.get("controlled_tags", []) or []),
        rules_path=data.get("rules_path"),
        config_path=data.get("config_path"),
        asset_id=data.get("asset_id"),
        progress=dict(data.get("progress", {}) or {}),
        error=data.get("error"),
    )


def iter_session_items(
    project_root: Path, session: IngestSession
) -> list[IngestQueueItem]:
    return [load_queue_item(project_root, item_id) for item_id in session.item_ids]
