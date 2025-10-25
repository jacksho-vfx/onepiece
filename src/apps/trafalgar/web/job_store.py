"""Persistent storage for Trafalgar render job records."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover - import only used for typing
    from .render import _JobRecord


logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialise_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


@dataclass(slots=True)
class JobStoreStats:
    """Aggregated metrics about store operations and pruning activity."""

    retention: timedelta | None
    retained_records: int = 0
    last_pruned_count: int = 0
    total_pruned: int = 0
    last_pruned_at: datetime | None = None
    last_load_at: datetime | None = None
    last_save_at: datetime | None = None
    last_rotation_at: datetime | None = None
    last_rotation_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        retention_seconds: int | None
        if self.retention is None:
            retention_seconds = None
        else:
            retention_seconds = int(self.retention.total_seconds())
        data["retention_seconds"] = retention_seconds
        data.pop("retention")
        data["last_pruned_at"] = _serialise_datetime(self.last_pruned_at)
        data["last_load_at"] = _serialise_datetime(self.last_load_at)
        data["last_save_at"] = _serialise_datetime(self.last_save_at)
        data["last_rotation_at"] = _serialise_datetime(self.last_rotation_at)
        return data


class JobStore:
    """Lightweight JSON backed store for render job records."""

    def __init__(
        self, path: os.PathLike[str] | str, *, retention: timedelta | None = None
    ) -> None:
        self._path = Path(path)
        self._retention = retention
        self._stats = JobStoreStats(retention=retention)

    @property
    def path(self) -> Path:
        """Return the path backing the store."""

        return self._path

    @property
    def stats(self) -> JobStoreStats:
        """Expose store metrics for health endpoints."""

        return self._stats

    def _apply_retention(
        self, records: list[_JobRecord], *, now: datetime | None = None
    ) -> tuple[list[_JobRecord], int]:
        if not self._retention or not records:
            return records, 0
        moment = now or _utcnow()
        cutoff = moment - self._retention
        retained = [record for record in records if record.created_at >= cutoff]
        removed = len(records) - len(retained)
        return retained, removed

    def _record_prune(self, count: int, *, now: datetime | None = None) -> None:
        if count <= 0:
            return
        moment = now or _utcnow()
        self._stats.last_pruned_at = moment
        self._stats.last_pruned_count = count
        self._stats.total_pruned += count

    def _write_payload(
        self, records: list[_JobRecord], *, now: datetime | None = None
    ) -> None:
        payload = [record.to_storage() for record in records]
        serialised = json.dumps(payload, indent=2, sort_keys=True)

        moment = now or _utcnow()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        backup_path = self._path.with_suffix(self._path.suffix + ".bak")
        backup_created = False

        if self._path.exists():
            try:
                os.replace(self._path, backup_path)
                backup_created = True
                self._stats.last_rotation_at = moment
                self._stats.last_rotation_error = None
            except OSError as exc:  # pragma: no cover - defensive guard
                self._stats.last_rotation_error = str(exc)
                raise

        try:
            tmp_path.write_text(serialised, encoding="utf-8")
            os.replace(tmp_path, self._path)
        except Exception:  # pragma: no cover - defensive guard
            try:
                if backup_created and backup_path.exists():
                    os.replace(backup_path, self._path)
            except OSError:
                pass
            raise
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

        if backup_created:
            try:
                backup_path.unlink()
            except FileNotFoundError:
                pass

        self._stats.last_save_at = moment
        self._stats.retained_records = len(records)

    def load(self) -> list[_JobRecord]:
        """Load job records from disk."""

        from .render import _JobRecord  # Local import to avoid circular dependency

        self._stats.last_load_at = _utcnow()
        if not self._path.exists():
            self._stats.retained_records = 0
            return []
        try:
            raw_data = self._path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - defensive guard
            logger.warning(
                "render.store.read_failed", path=str(self._path), error=str(exc)
            )
            self._stats.retained_records = 0
            return []
        try:
            payload = json.loads(raw_data or "[]")
        except json.JSONDecodeError as exc:
            logger.warning(
                "render.store.decode_failed", path=str(self._path), error=str(exc)
            )
            self._stats.retained_records = 0
            return []

        records: list[_JobRecord] = []
        if not isinstance(payload, list):
            logger.warning("render.store.invalid_payload", path=str(self._path))
            self._stats.retained_records = 0
            return []

        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                record = _JobRecord.from_storage(item)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.warning("render.store.record_invalid", error=str(exc))
                continue
            records.append(record)
        records.sort(key=lambda entry: entry.created_at)

        now = _utcnow()
        retained, removed = self._apply_retention(records, now=now)
        if removed:
            self._record_prune(removed, now=now)
            try:
                self._write_payload(retained, now=now)
            except OSError as exc:  # pragma: no cover - defensive guard
                logger.warning(
                    "render.store.compaction_failed",
                    path=str(self._path),
                    error=str(exc),
                )
        else:
            self._stats.retained_records = len(retained)
        return retained

    def save(self, records: Iterable[_JobRecord]) -> None:
        """Persist the supplied job records to disk."""

        materialised = list(records)
        materialised.sort(key=lambda entry: entry.created_at)
        now = _utcnow()
        retained, removed = self._apply_retention(materialised, now=now)
        if removed:
            self._record_prune(removed, now=now)
        self._write_payload(retained, now=now)
