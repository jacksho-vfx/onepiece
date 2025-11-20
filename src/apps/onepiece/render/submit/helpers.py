"""Shared helpers for the render submission CLI."""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from typing import Any, Final, Mapping, cast

from apps.onepiece.config import load_profile
from apps.onepiece.utils.errors import (
    OnePieceConfigError,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)
from libraries.automation.render import deadline, mock, opencue, tractor
from libraries.automation.render.base import (
    AdapterCapabilities,
    RenderSubmissionError,
)
from libraries.automation.render.models import CapabilityProvider, RenderAdapter
from libraries.automation.render.optimization import (
    AdapterDefaults,
    FarmMetrics,
    SubmissionOptimizationDecision,
    compute_submission_adjustments,
)

DCC_CHOICES: Final[tuple[str, ...]] = (
    "maya",
    "nuke",
    "houdini",
    "blender",
    "cinema4d",
    "max",
    "vray",
)

FARM_CHOICES: Final[tuple[str, ...]] = ("deadline", "tractor", "opencue", "mock")

FARM_ADAPTERS: Final[dict[str, RenderAdapter]] = {
    "deadline": deadline.submit_job,
    "tractor": tractor.submit_job,
    "opencue": opencue.submit_job,
    "mock": mock.submit_job,
}

FARM_CAPABILITY_PROVIDERS: Final[dict[str, CapabilityProvider]] = {
    "deadline": deadline.get_capabilities,
    "tractor": tractor.get_capabilities,
    "opencue": opencue.get_capabilities,
    "mock": mock.get_capabilities,
}

_CAPABILITIES_CACHE_TTL_SECONDS: Final[float] = 60.0
_CAPABILITIES_CACHE_MAXSIZE: Final[int] = 32
_CAPABILITIES_CACHE_LOCK = threading.RLock()
_CAPABILITIES_CACHE: OrderedDict[str, tuple[float, AdapterCapabilities]] = OrderedDict()

_FRAME_SEGMENT_PATTERN = re.compile(
    r"^\s*(?P<start>-?\d+)(?:\s*-\s*(?P<end>-?\d+))?(?:x(?P<step>\d+))?\s*$"
)


def _optional_int(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise OnePieceValidationError(
            f"Profile optimisation value '{label}' must be an integer."
        )
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError as exc:
            raise OnePieceValidationError(
                f"Profile optimisation value '{label}' must be an integer."
            ) from exc
    raise OnePieceValidationError(
        f"Profile optimisation value '{label}' must be an integer."
    )


def _optional_float(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise OnePieceValidationError(
            f"Profile optimisation value '{label}' must be numeric."
        )
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError as exc:
            raise OnePieceValidationError(
                f"Profile optimisation value '{label}' must be numeric."
            ) from exc
    raise OnePieceValidationError(
        f"Profile optimisation value '{label}' must be numeric."
    )


def parse_frame_count(spec: str) -> int | None:
    """Best-effort parser for frame range specifications."""

    total = 0
    segments = [part.strip() for part in spec.split(",") if part.strip()]
    if not segments:
        return None

    for segment in segments:
        match = _FRAME_SEGMENT_PATTERN.match(segment)
        if not match:
            return None
        start = int(match.group("start"))
        end = match.group("end")
        end_value = int(end) if end is not None else start
        step = int(match.group("step") or 1)
        if step <= 0:
            return None

        if start <= end_value:
            span = end_value - start
        else:
            span = start - end_value
        total += span // step + 1

    return total if total > 0 else None


def _extract_metrics_from_profile(data: Mapping[str, Any]) -> FarmMetrics:
    render_block = data.get("render")
    if not isinstance(render_block, Mapping):
        return FarmMetrics()
    optimisation_block = render_block.get("optimization")
    if not isinstance(optimisation_block, Mapping):
        return FarmMetrics()

    queue_depth = _optional_int(
        optimisation_block.get("queue_depth"), label="queue_depth"
    )
    average_ms = optimisation_block.get("average_frame_ms")
    if average_ms is None:
        average_ms = optimisation_block.get("average_frame_time_ms")
    average_frame_ms = _optional_float(average_ms, label="average_frame_ms")

    return FarmMetrics(
        queue_depth=queue_depth,
        average_frame_time_ms=average_frame_ms,
    )


def resolve_metrics(
    *,
    optimize: bool,
    profile_name: str | None,
    queue_depth: int | None,
    average_frame_ms: float | None,
) -> tuple[FarmMetrics, tuple[str, ...]]:
    metrics = FarmMetrics()
    sources: list[str] = []

    if optimize:
        try:
            profile_context = load_profile(profile=profile_name)
        except OnePieceConfigError as exc:
            raise OnePieceValidationError(str(exc)) from exc

        profile_metrics = _extract_metrics_from_profile(profile_context.data)
        if (
            profile_metrics.queue_depth is not None
            or profile_metrics.average_frame_time_ms is not None
        ):
            metrics = profile_metrics
            sources.append("profile")

    if queue_depth is not None:
        metrics = FarmMetrics(
            queue_depth=queue_depth,
            average_frame_time_ms=metrics.average_frame_time_ms,
        )
        sources.append("cli.queue_depth")

    if average_frame_ms is not None:
        metrics = FarmMetrics(
            queue_depth=metrics.queue_depth,
            average_frame_time_ms=average_frame_ms,
        )
        sources.append("cli.average_frame_ms")

    return metrics, tuple(sources)


def get_adapter(farm: str) -> RenderAdapter:
    adapter = FARM_ADAPTERS.get(farm)
    if adapter is None:
        raise OnePieceValidationError(f"Unknown render farm '{farm}'.")
    return adapter


def refresh_capabilities_cache(*, farm: str | None = None) -> None:
    """Clear cached capability information for one or all farms."""

    with _CAPABILITIES_CACHE_LOCK:
        if farm is None:
            _CAPABILITIES_CACHE.clear()
        else:
            _CAPABILITIES_CACHE.pop(farm, None)


def fetch_adapter_capabilities(farm: str) -> AdapterCapabilities:
    provider = FARM_CAPABILITY_PROVIDERS.get(farm)
    if provider is None:
        raise OnePieceValidationError(f"Unknown render farm '{farm}'.")
    try:
        raw_capabilities = provider() or {}
    except RenderSubmissionError as exc:
        raise OnePieceExternalServiceError(
            f"Failed to query capabilities from '{farm}' adapter: {exc}"
        ) from exc
    return dict(raw_capabilities)


def get_adapter_capabilities(farm: str) -> AdapterCapabilities:
    now = time.monotonic()
    with _CAPABILITIES_CACHE_LOCK:
        cached = _CAPABILITIES_CACHE.get(farm)
        if cached is not None:
            expires_at, capabilities = cached
            if expires_at > now:
                _CAPABILITIES_CACHE.move_to_end(farm)
                return dict(capabilities)

    capabilities = fetch_adapter_capabilities(farm)
    expiry = time.monotonic() + _CAPABILITIES_CACHE_TTL_SECONDS

    with _CAPABILITIES_CACHE_LOCK:
        _CAPABILITIES_CACHE[farm] = (expiry, dict(capabilities))
        _CAPABILITIES_CACHE.move_to_end(farm)
        while len(_CAPABILITIES_CACHE) > _CAPABILITIES_CACHE_MAXSIZE:
            _CAPABILITIES_CACHE.popitem(last=False)

    return dict(capabilities)


def resolve_priority_and_chunk_size(
    *,
    farm: str,
    priority: int | None,
    chunk_size: int | None,
    capabilities: AdapterCapabilities | None = None,
    capability_provider: CapabilityProvider | None = None,
    frame_count: int | None = None,
    optimize: bool = True,
    metrics: FarmMetrics | None = None,
) -> tuple[
    int | None,
    int | None,
    AdapterCapabilities,
    SubmissionOptimizationDecision | None,
]:
    resolved_capabilities: AdapterCapabilities
    if capabilities is not None:
        resolved_capabilities = dict(capabilities)
    else:
        provider = capability_provider
        if provider is None:
            resolved_capabilities = get_adapter_capabilities(farm)
        else:
            try:
                resolved_capabilities = provider() or {}
            except RenderSubmissionError as exc:
                raise OnePieceExternalServiceError(
                    f"Failed to query capabilities from '{farm}' adapter: {exc}"
                ) from exc

    resolved_priority = priority
    if resolved_priority is None:
        resolved_priority = resolved_capabilities.get("default_priority", 50)

    adapter_default_priority = resolved_capabilities.get("default_priority", 50)

    min_priority = resolved_capabilities.get("priority_min")
    max_priority = resolved_capabilities.get("priority_max")
    if min_priority is not None and resolved_priority < min_priority:
        raise OnePieceValidationError(
            f"Priority {resolved_priority} is below the supported minimum of {min_priority} (--priority)."
        )
    if max_priority is not None and resolved_priority > max_priority:
        raise OnePieceValidationError(
            f"Priority {resolved_priority} exceeds the supported maximum of {max_priority} (--priority)."
        )

    chunk_enabled = resolved_capabilities.get("chunk_size_enabled", False)
    if chunk_size is not None and not chunk_enabled:
        raise OnePieceValidationError(
            "Chunk sizing is not supported by this adapter (--chunk-size)."
        )
    chunk_min = resolved_capabilities.get("chunk_size_min")
    chunk_max = resolved_capabilities.get("chunk_size_max")
    adapter_default_chunk = (
        cast(int | None, resolved_capabilities.get("default_chunk_size"))
        if chunk_enabled
        else None
    )

    def _validate_chunk_size(value: int) -> None:
        if chunk_min is not None and value < chunk_min:
            raise OnePieceValidationError(
                f"Chunk size {value} is below the supported minimum of {chunk_min} (--chunk-size)."
            )
        if chunk_max is not None and value > chunk_max:
            raise OnePieceValidationError(
                f"Chunk size {value} exceeds the supported maximum of {chunk_max} (--chunk-size)."
            )

    if chunk_enabled:
        if chunk_size is not None:
            _validate_chunk_size(chunk_size)
        if adapter_default_chunk is not None:
            _validate_chunk_size(adapter_default_chunk)
    resolved_chunk: int | None
    if chunk_size is not None:
        resolved_chunk = chunk_size
    elif chunk_enabled:
        resolved_chunk = adapter_default_chunk
    else:
        resolved_chunk = None

    optimisation_summary: SubmissionOptimizationDecision | None = None
    if (
        optimize
        and frame_count is not None
        and frame_count > 0
        and (priority is None or (chunk_enabled and chunk_size is None))
    ):
        defaults = AdapterDefaults(
            default_priority=adapter_default_priority,
            priority_min=min_priority,
            priority_max=max_priority,
            default_chunk_size=adapter_default_chunk,
            chunk_size_min=chunk_min,
            chunk_size_max=chunk_max,
            chunk_size_enabled=chunk_enabled and adapter_default_chunk is not None,
        )
        try:
            optimisation_summary = compute_submission_adjustments(
                frame_count,
                defaults,
                metrics=metrics,
            )
        except ValueError:
            optimisation_summary = None
        else:
            if priority is None:
                resolved_priority = optimisation_summary.priority
            if chunk_size is None and chunk_enabled:
                resolved_chunk = optimisation_summary.chunk_size

    if resolved_chunk is not None:
        if not chunk_enabled:
            raise OnePieceValidationError(
                "Chunk sizing is not supported by this adapter (--chunk-size)."
            )
        if chunk_min is not None and resolved_chunk < chunk_min:
            raise OnePieceValidationError(
                f"Chunk size {resolved_chunk} is below the supported minimum of {chunk_min} (--chunk-size)."
            )
        if chunk_max is not None and resolved_chunk > chunk_max:
            raise OnePieceValidationError(
                f"Chunk size {resolved_chunk} exceeds the supported maximum of {chunk_max} (--chunk-size)."
            )
    elif chunk_size is not None:
        # Explicitly requested None but the adapter does not support chunking.
        raise OnePieceValidationError(
            "Chunk sizing is not supported by this adapter (--chunk-size)."
        )

    return (
        resolved_priority,
        resolved_chunk,
        resolved_capabilities,
        optimisation_summary,
    )


def coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def extract_history(job: Mapping[str, Any]) -> list[str]:
    history: list[str] = []
    raw_history = job.get("history") or job.get("status_history")
    if isinstance(raw_history, list):
        for entry in raw_history:
            if isinstance(entry, Mapping):
                status = coerce_text(entry.get("status") or entry.get("state"))
                timestamp = coerce_text(entry.get("timestamp") or entry.get("time"))
                if status and timestamp:
                    history.append(f"{status} at {timestamp}")
                elif status:
                    history.append(status)
                elif timestamp:
                    history.append(timestamp)
            elif isinstance(entry, (list, tuple)):
                parts = [part for part in entry if coerce_text(part)]
                if parts:
                    history.append(" at ".join(coerce_text(part) for part in parts))
            else:
                text = coerce_text(entry)
                if text:
                    history.append(text)
    return history


__all__ = [
    "DCC_CHOICES",
    "FARM_CHOICES",
    "FARM_ADAPTERS",
    "FARM_CAPABILITY_PROVIDERS",
    "coerce_text",
    "extract_history",
    "fetch_adapter_capabilities",
    "get_adapter",
    "get_adapter_capabilities",
    "parse_frame_count",
    "refresh_capabilities_cache",
    "resolve_metrics",
    "resolve_priority_and_chunk_size",
]
