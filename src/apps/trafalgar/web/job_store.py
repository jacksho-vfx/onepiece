"""Persistent storage for Trafalgar render job records."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover - import only used for typing
    from .render import _JobRecord


logger = structlog.get_logger(__name__)


class JobStore:
    """Lightweight JSON backed store for render job records."""

    def __init__(self, path: os.PathLike[str] | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """Return the path backing the store."""

        return self._path

    def load(self) -> list[_JobRecord]:
        """Load job records from disk."""

        from .render import _JobRecord  # Local import to avoid circular dependency

        if not self._path.exists():
            return []
        try:
            raw_data = self._path.read_text(encoding="utf-8")
        except OSError as exc:  # pragma: no cover - defensive guard
            logger.warning("render.store.read_failed", path=str(self._path), error=str(exc))
            return []
        try:
            payload = json.loads(raw_data or "[]")
        except json.JSONDecodeError as exc:
            logger.warning("render.store.decode_failed", path=str(self._path), error=str(exc))
            return []

        records: list[_JobRecord] = []
        if not isinstance(payload, list):
            logger.warning("render.store.invalid_payload", path=str(self._path))
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
        return records

    def save(self, records: Iterable[_JobRecord]) -> None:
        """Persist the supplied job records to disk."""

        payload = [record.to_storage() for record in records]

        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        data = json.dumps(payload, indent=2, sort_keys=True)
        tmp_path.write_text(data, encoding="utf-8")
        os.replace(tmp_path, self._path)
