"""Helpers for caching known dashboard projects and related settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

import structlog

logger = structlog.get_logger(__name__)

__all__ = [
    "_load_known_projects",
    "_project_registry_path",
    "_load_project_registry",
    "_store_project_registry",
    "_load_cache_configuration",
    "_parse_float",
    "_parse_int",
]


def _load_known_projects() -> set[str]:
    """Return project names configured via the environment."""

    value = os.getenv("ONEPIECE_DASHBOARD_PROJECTS", "")
    projects = {item.strip() for item in value.split(",") if item.strip()}
    return projects


def _project_registry_path() -> Path | None:
    """Return the path used for caching discovered project names."""

    override = os.getenv("ONEPIECE_DASHBOARD_PROJECT_REGISTRY")
    if override:
        return Path(override)

    cache_root = os.getenv("XDG_CACHE_HOME")
    if cache_root:
        base = Path(cache_root)
    else:
        try:
            base = Path.home() / ".cache"
        except RuntimeError:  # pragma: no cover - extremely rare environments
            return None

    return base / "onepiece" / "dashboard-projects.json"


def _load_project_registry() -> set[str]:
    """Return cached project names from the local registry if available."""

    path = _project_registry_path()
    if path is None or not path.is_file():
        return set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            "dashboard.project_registry.load_failed", path=str(path), error=str(exc)
        )
        return set()

    projects: set[str] = set()
    for item in data:
        if isinstance(item, str):
            text = item.strip()
            if text:
                projects.add(text)
        elif item is not None:
            text = str(item).strip()
            if text:
                projects.add(text)
    return projects


def _store_project_registry(projects: Iterable[str]) -> None:
    """Persist discovered project names for reuse when ShotGrid is offline."""

    path = _project_registry_path()
    if path is None:
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = sorted({str(item).strip() for item in projects if str(item).strip()})
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning(
            "dashboard.project_registry.store_failed", path=str(path), error=str(exc)
        )


def _parse_float(value: Any, default: float) -> float:
    """Return *value* coerced to ``float`` with ``default`` as a fallback."""

    try:
        if value is None:
            raise ValueError("missing")
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            text = str(value).strip()
            if not text:
                raise ValueError("empty")
            result = float(text)
    except (TypeError, ValueError):
        return max(0.0, float(default))
    return max(0.0, float(result))


def _parse_int(value: Any, default: int) -> int:
    """Return *value* coerced to ``int`` with ``default`` as a fallback."""

    try:
        if value is None:
            raise ValueError("missing")
        if isinstance(value, int):
            result = value
        else:
            text = str(value).strip()
            if not text:
                raise ValueError("empty")
            result = int(text)
    except (TypeError, ValueError):
        return max(0, int(default))
    return max(0, int(result))


def _load_cache_configuration(*, state: Any | None = None) -> tuple[float, int, int]:
    """Return cache configuration from the environment or provided state."""

    default_ttl = 30.0
    default_max_records = 5000
    default_max_projects = 50

    ttl_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_TTL")
    max_records_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_MAX_RECORDS")
    max_projects_value = os.getenv("ONEPIECE_DASHBOARD_CACHE_MAX_PROJECTS")

    ttl = _parse_float(ttl_value, default_ttl)
    max_records = _parse_int(max_records_value, default_max_records)
    max_projects = _parse_int(max_projects_value, default_max_projects)

    if state is not None:
        ttl = _parse_float(getattr(state, "dashboard_cache_ttl", ttl), ttl)
        max_records = _parse_int(
            getattr(state, "dashboard_cache_max_records", max_records),
            max_records,
        )
        max_projects = _parse_int(
            getattr(state, "dashboard_cache_max_projects", max_projects),
            max_projects,
        )

    return ttl, max_records, max_projects
