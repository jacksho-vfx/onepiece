"""Shared dependencies and helpers for the Perona dashboard package."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from threading import Lock
from typing import Any, Mapping, NamedTuple, Sequence, TypeVar

from fastapi import HTTPException, Query, Security, status
from starlette.websockets import WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

from apps.perona.web import wrangler
from libraries.analytics.perona.engine.engine import PeronaEngine
from libraries.analytics.perona.engine.settings import DEFAULT_SETTINGS_PATH
from libraries.analytics.perona.models import RenderMetric, SettingsSummary
from libraries.analytics.perona.ml_foundations import FeatureStatistics


_metrics_token_env = "PERONA_METRICS_TOKEN"
_metrics_bearer_scheme = HTTPBearer(auto_error=False)


class RenderMetricBatch(BaseModel):
    """Payload wrapper for render metrics ingested via the API."""

    metrics: tuple[RenderMetric, ...] = Field(default_factory=tuple)

    model_config = ConfigDict(populate_by_name=True)

    def to_serialisable(self) -> list[dict[str, Any]]:
        """Return JSON-friendly dictionaries for persistence."""

        return [
            metric.model_dump(mode="json", by_alias=True) for metric in self.metrics
        ]


class RenderMetricStore:
    """Simple append-only store that persists render metrics to disk."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = Lock()

    @property
    def path(self) -> Path:
        return self._path

    def persist(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Append metrics to the backing store as NDJSON."""

        if not records:
            return

        lines = [
            json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            for record in records
        ]
        payload = "\n".join(lines) + "\n"

        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(payload)


def _resolve_metrics_store_path() -> Path:
    """Return the configured metrics store path, falling back to cache dir."""

    env_path = os.getenv("PERONA_METRICS_PATH")
    if env_path:
        return Path(env_path).expanduser()

    cache_home = os.getenv("XDG_CACHE_HOME")
    base_dir = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return base_dir / "perona" / "render-metrics.ndjson"


_metrics_store = RenderMetricStore(_resolve_metrics_store_path())


def _expected_metrics_token() -> str:
    """Return the configured metrics token or raise if not set."""

    token = os.getenv(_metrics_token_env)
    if not token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Metrics authentication token is not configured.",
        )
    return token


def require_metrics_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_metrics_bearer_scheme),
) -> None:
    """Validate bearer credentials for metrics ingestion and streaming endpoints."""

    expected_token = _expected_metrics_token()
    provided = credentials.credentials if credentials else None
    if not provided or not hmac.compare_digest(provided, expected_token):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid authentication token."
        )


async def require_metrics_websocket_auth(websocket: WebSocket) -> None:
    """Validate bearer credentials for websocket clients."""

    try:
        expected_token = _expected_metrics_token()
    except HTTPException:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        raise WebSocketDisconnect(code=status.WS_1011_INTERNAL_ERROR)

    header = websocket.headers.get("Authorization", "")
    scheme, _, provided = header.partition(" ")
    token = provided.strip() if scheme.lower() == "bearer" else None

    if not token or not hmac.compare_digest(token, expected_token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketDisconnect(code=status.WS_1008_POLICY_VIOLATION)


class _CostInsightsMemo:
    """In-memory cache for cost insights keyed by ``top_n``."""

    __slots__ = ("statistics", "recommendations_by_top_n")

    def __init__(self) -> None:
        self.statistics: tuple[FeatureStatistics, ...] | None = None
        self.recommendations_by_top_n: dict[int, tuple[str, ...]] = {}

    def clear(self) -> None:
        self.statistics = None
        self.recommendations_by_top_n.clear()


class _EngineCacheEntry(NamedTuple):
    engine: PeronaEngine
    signature: tuple[str | None, str, int | None]
    settings_path: Path | None
    warnings: tuple[str, ...]
    insights: _CostInsightsMemo


_engine_lock = Lock()
_engine_cache: _EngineCacheEntry | None = None
T = TypeVar("T")


def _sync_engine_cache_from_module() -> _EngineCacheEntry | None:
    """Return the latest engine cache, honoring overrides from the public module."""

    global _engine_cache

    module = sys.modules.get("apps.perona.web.dashboard")
    if module is not None:
        external_cache = module.__dict__.get("_engine_cache", _engine_cache)
        if external_cache is not _engine_cache:
            _engine_cache = external_cache
    return _engine_cache


def _update_module_engine_cache(value: _EngineCacheEntry | None) -> None:
    """Keep the publicly exposed module cache in sync with internal state."""

    module = sys.modules.get("apps.perona.web.dashboard")
    if module is not None:
        module.__dict__["_engine_cache"] = value


def _resolve_override(name: str, current: T) -> Any:
    """Return an attribute override registered on the public dashboard module."""

    module = sys.modules.get("apps.perona.web.dashboard")
    if module is not None:
        override = module.__dict__.get(name, current)
        if override is not current:
            globals()[name] = override  # keep the internal module in sync
            return override  # type: ignore[return-value]
    return current


def _resolved_settings_path() -> Path | None:
    """Return the configured settings path if it can be resolved."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(DEFAULT_SETTINGS_PATH)

    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved.exists():
            return resolved
    return None


def _settings_signature() -> tuple[str | None, str, int | None, int | None, str | None]:
    """Return the cache signature for the current settings configuration."""

    env_path = os.getenv("PERONA_SETTINGS_PATH")
    resolved_path = _resolved_settings_path()
    signature_path = resolved_path or DEFAULT_SETTINGS_PATH.expanduser()

    mtime_ns: int | None = None
    file_size: int | None = None
    digest: str | None = None
    try:
        stat_result = signature_path.stat()
        mtime_ns = getattr(stat_result, "st_mtime_ns", None)
        if mtime_ns is None:
            mtime_ns = int(stat_result.st_mtime * 1_000_000_000)
        file_size = stat_result.st_size
        checksum = hashlib.sha256()
        with signature_path.open("rb") as handle:
            while True:
                chunk = handle.read(8192)
                if not chunk:
                    break
                checksum.update(chunk)
        digest = checksum.hexdigest()
    except OSError:
        mtime_ns = None

    return (env_path, str(signature_path), mtime_ns, file_size, digest)


def _get_engine_cache_entry(force_refresh: bool = False) -> _EngineCacheEntry:
    """Return the cached engine entry, refreshing when configuration changes."""

    global _engine_cache

    signature_fn = _resolve_override("_settings_signature", _settings_signature)
    signature = signature_fn()
    with _engine_lock:
        cache_entry = _sync_engine_cache_from_module()
        if force_refresh or cache_entry is None or cache_entry.signature != signature:
            load_result = PeronaEngine.from_settings()
            cache_entry = _EngineCacheEntry(
                engine=load_result.engine,
                signature=signature,
                settings_path=load_result.settings_path,
                warnings=load_result.warnings,
                insights=_CostInsightsMemo(),
            )
            _engine_cache = cache_entry
            _update_module_engine_cache(cache_entry)
        return cache_entry


def _load_engine(force_refresh: bool) -> PeronaEngine:
    """Return a cached engine instance, reloading when configuration changes."""

    return _get_engine_cache_entry(force_refresh).engine


def invalidate_engine_cache() -> None:
    """Clear the cached engine so it will be rebuilt on next use."""

    global _engine_cache
    with _engine_lock:
        _engine_cache = None
        _update_module_engine_cache(None)


def _resolve_cost_insights(
    engine: PeronaEngine,
    *,
    top_n: int,
    refresh_telemetry: bool,
) -> tuple[tuple[FeatureStatistics, ...], tuple[str, ...]]:
    """Return cost insights using cached results when available."""

    cached_statistics: tuple[FeatureStatistics, ...] | None = None
    cached_recommendations: tuple[str, ...] | None = None

    with _engine_lock:
        cache_entry = _sync_engine_cache_from_module()
        if cache_entry is not None and cache_entry.engine is engine:
            if refresh_telemetry:
                cache_entry.insights.clear()
            memo = cache_entry.insights
            cached_statistics = memo.statistics
            cached_recommendations = memo.recommendations_by_top_n.get(top_n)
            if cached_statistics is not None and cached_recommendations is not None:
                return cached_statistics, cached_recommendations

    statistics, recommendations = engine.cost_insights(top_n=top_n)

    with _engine_lock:
        cache_entry = _sync_engine_cache_from_module()
        if cache_entry is not None and cache_entry.engine is engine:
            memo = cache_entry.insights
            memo.statistics = statistics
            memo.recommendations_by_top_n[top_n] = recommendations

    return statistics, recommendations


def _settings_summary_from_cache(force_refresh: bool = False) -> SettingsSummary:
    """Return a settings summary derived from the cached engine entry."""

    cache_entry = _get_engine_cache_entry(force_refresh)
    return SettingsSummary.from_engine(
        cache_entry.engine,
        settings_path=cache_entry.settings_path,
        warnings=cache_entry.warnings,
    )


def reload_settings() -> SettingsSummary:
    """Invalidate and rebuild the engine cache, returning the refreshed summary."""

    invalidate_engine_cache()
    return _settings_summary_from_cache(force_refresh=True)


def get_engine(refresh: bool = Query(False, alias="refresh_engine")) -> PeronaEngine:
    """FastAPI dependency yielding the shared Perona engine instance."""

    loader = _resolve_override("_load_engine", _load_engine)
    return loader(refresh)


def get_settings_summary() -> SettingsSummary:
    """Return the resolved configuration powering the dashboard."""

    return _settings_summary_from_cache()


def get_cost_insights(
    engine: PeronaEngine,
    *,
    top_n: int,
    refresh_telemetry: bool,
) -> tuple[tuple[FeatureStatistics, ...], tuple[str, ...]]:
    """Expose cached cost insights for API consumers."""

    return _resolve_cost_insights(
        engine, top_n=top_n, refresh_telemetry=refresh_telemetry
    )


def get_engine_cache_entry() -> _EngineCacheEntry:
    """Expose the current engine cache entry for internal consumers."""

    return _get_engine_cache_entry()


def persist_metrics(records: Sequence[Mapping[str, Any]]) -> None:
    """Persist telemetry records using the shared metrics store."""

    _metrics_store.persist(records)


def metrics_store_path() -> Path:
    """Return the path backing the metrics store."""

    return _metrics_store.path


def list_wrangler_scripts() -> list[wrangler.WranglerScriptMetadata]:
    """Return sorted Wrangler script metadata."""

    scripts = list(wrangler.iter_registered_scripts())
    scripts.sort(key=lambda meta: (meta.name or meta.script_id).casefold())
    return scripts


__all__ = [
    "RenderMetricBatch",
    "RenderMetricStore",
    "get_engine",
    "get_settings_summary",
    "get_cost_insights",
    "get_engine_cache_entry",
    "invalidate_engine_cache",
    "list_wrangler_scripts",
    "metrics_store_path",
    "persist_metrics",
    "reload_settings",
]
