"""Persistence helpers for ingest run metadata shared across interfaces."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, List, Mapping, cast

from libraries.ingest.service import IngestReport, IngestedMedia, MediaInfo

logger = logging.getLogger(__name__)


DEFAULT_REGISTRY_ENV = "ONEPIECE_INGEST_REGISTRY"
DEFAULT_REGISTRY_PATH = Path("~/.cache/onepiece/ingest_runs.json").expanduser()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Support both timezone aware and naive ISO timestamps. ``fromisoformat``
        # understands most common layouts except the ``Z`` suffix which we
        # normalise beforehand.
        value = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(value)
    except ValueError:
        logger.warning("ingest.registry.invalid_timestamp", value=value)
        return None


def _load_media_info(payload: Mapping[str, Any]) -> MediaInfo | None:
    try:
        return MediaInfo(
            show_code=str(payload["show_code"]),
            episode=str(payload["episode"]),
            scene=str(payload["scene"]),
            shot=str(payload["shot"]),
            descriptor=str(payload["descriptor"]),
            extension=str(payload["extension"]),
        )
    except KeyError as exc:  # pragma: no cover - defensive programming
        logger.warning("ingest.registry.missing_media_info", missing=str(exc))
        return None


def _load_processed(payload: Iterable[Mapping[str, Any]]) -> list[IngestedMedia]:
    results: list[IngestedMedia] = []
    for item in payload:
        media_info_data = item.get("media_info", {})
        if not isinstance(media_info_data, Mapping):
            logger.warning("ingest.registry.invalid_media_info", data=media_info_data)
            continue
        media_info = _load_media_info(media_info_data)
        if media_info is None:
            continue
        path = item.get("path")
        bucket = item.get("bucket")
        key = item.get("key")
        if not path or not bucket or not key:
            logger.warning("ingest.registry.incomplete_media", data=item)
            continue
        results.append(
            IngestedMedia(
                path=Path(str(path)),
                bucket=str(bucket),
                key=str(key),
                media_info=media_info,
            )
        )
    return results


def _load_invalid(entries: Iterable[Iterable[Any]]) -> list[tuple[Path, str]]:
    invalid: list[tuple[Path, str]] = []
    for entry in entries:
        try:
            file_path, reason = entry
        except (TypeError, ValueError):
            logger.warning("ingest.registry.invalid_invalid_entry", data=entry)
            continue
        invalid.append((Path(str(file_path)), str(reason)))
    return invalid


def _load_report(payload: Mapping[str, Any]) -> IngestReport:
    processed_payload = payload.get("processed", [])
    if not isinstance(processed_payload, Iterable):
        processed_payload = []
    invalid_payload = payload.get("invalid", [])
    if not isinstance(invalid_payload, Iterable):
        invalid_payload = []
    processed = _load_processed(cast(List[Mapping[str, Any]], processed_payload))
    invalid = _load_invalid(cast(List[Iterable[Any]], invalid_payload))
    return IngestReport(processed=processed, invalid=invalid)


@dataclass
class IngestRunRecord:
    """Structured ingest run information loaded from the registry."""

    run_id: str
    started_at: datetime | None
    completed_at: datetime | None
    report: IngestReport


class IngestRunRegistry:
    """Access a JSON registry containing ingest run metadata."""

    def __init__(self, path: Path | None = None) -> None:
        env_path = os.environ.get(DEFAULT_REGISTRY_ENV)
        if path is None:
            path = Path(env_path).expanduser() if env_path else DEFAULT_REGISTRY_PATH
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def _load_payload(self) -> list[Mapping[str, Any]]:
        if not self._path.exists():
            return []
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("ingest.registry.load_failed", path=str(self._path), error=str(exc))
            return []

        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, Mapping)]

        if isinstance(payload, Mapping):
            runs = payload.get("runs", [])
            if isinstance(runs, list):
                return [item for item in runs if isinstance(item, Mapping)]

        logger.warning("ingest.registry.unexpected_payload", payload_type=type(payload).__name__)
        return []

    def load_all(self) -> list[IngestRunRecord]:
        records: list[IngestRunRecord] = []
        for entry in self._load_payload():
            run_id = entry.get("id") or entry.get("run_id")
            if not run_id:
                logger.warning("ingest.registry.missing_run_id", data=entry)
                continue
            report_payload = entry.get("report", {})
            if not isinstance(report_payload, Mapping):
                logger.warning("ingest.registry.invalid_report", data=report_payload)
                report_payload = {}
            record = IngestRunRecord(
                run_id=str(run_id),
                started_at=_parse_datetime(entry.get("started_at")),
                completed_at=_parse_datetime(entry.get("completed_at")),
                report=_load_report(report_payload),
            )
            records.append(record)
        return records

    def load_recent(self, limit: int | None = None) -> list[IngestRunRecord]:
        records = self.load_all()
        records.sort(
            key=lambda record: record.started_at or datetime.min,
            reverse=True,
        )
        if limit is not None:
            return records[:limit]
        return records

    def get(self, run_id: str) -> IngestRunRecord | None:
        for record in self.load_all():
            if record.run_id == run_id:
                return record
        return None

