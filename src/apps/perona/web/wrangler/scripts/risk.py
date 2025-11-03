"""Wrangler scripts that analyse render risk and cache stability."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from apps.perona.web import dashboard as dashboard_module

from ..registry import WranglerScriptResult
from .telemetry import _format_timestamp_iso

_CACHE_STABILITY_THRESHOLD = 0.75
_OWNER_KEYS = ("owner", "artist", "lead", "supervisor", "producer", "coordinator")


def _streak_recommendation(streak: int) -> str:
    if streak >= 5:
        return "Escalate to QA for deep investigation."
    if streak >= 3:
        return "Escalate to the render wrangler for triage."
    if streak >= 1:
        return "Retry the shot and monitor for recurring errors."
    return "All clear — keep the shot in rotation."


def _run_flag_render_error_streaks_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    samples = sorted(
        engine.stream_render_metrics(),
        key=lambda sample: (sample.sequence, sample.shot_id, sample.timestamp),
    )

    streaks: dict[tuple[str, str], dict[str, Any]] = {}

    for sample in samples:
        key = (sample.sequence, sample.shot_id)
        entry = streaks.setdefault(
            key,
            {
                "sequence": sample.sequence,
                "shot": sample.shot_id,
                "sample_count": 0,
                "current_streak": 0,
                "longest_streak": 0,
                "last_timestamp": None,
            },
        )

        entry["sample_count"] += 1
        entry["last_timestamp"] = sample.timestamp

        if sample.error_count > 0:
            entry["current_streak"] += 1
            if entry["current_streak"] > entry["longest_streak"]:
                entry["longest_streak"] = entry["current_streak"]
        else:
            entry["current_streak"] = 0

    ranked: list[dict[str, Any]] = []
    for entry in streaks.values():
        longest = int(entry["longest_streak"])
        last_timestamp = _format_timestamp_iso(entry["last_timestamp"])
        ranked.append(
            {
                "sequence": entry["sequence"],
                "shot": entry["shot"],
                "longest_error_streak": longest,
                "sample_count": int(entry["sample_count"]),
                "last_timestamp": last_timestamp,
                "recommendation": _streak_recommendation(longest),
            }
        )

    ranked.sort(
        key=lambda item: (
            item["longest_error_streak"],
            item["sample_count"],
            item["last_timestamp"] or "",
        ),
        reverse=True,
    )

    worst = ranked[0] if ranked else None

    if worst and worst["longest_error_streak"] > 0:
        message = (
            "Worst streak: "
            f"{worst['sequence']} {worst['shot']} logged "
            f"{worst['longest_error_streak']} consecutive error sample(s)"
        )
        if worst["last_timestamp"]:
            message += f" (last seen {worst['last_timestamp']})."
        else:
            message += "."
    else:
        message = "All clear — no consecutive render errors detected."

    payload = {
        "summary": message,
        "streaks": ranked,
        "worst_streak": worst,
    }

    return WranglerScriptResult(
        script_id="flag_render_error_streaks",
        status="success",
        message=message,
        payload=payload,
    )


def _extract_cache_metrics(
    lifecycle: Any | None,
) -> tuple[str | None, int | None, float | None]:
    """Return cache-related lifecycle metrics for the supplied shot."""

    if lifecycle is None:
        return None, None, None

    stage_name: str | None = None
    resim_count: int | None = None
    avg_cache_gb: float | None = None

    stages = getattr(lifecycle, "stages", ())
    for stage in stages:
        metrics = getattr(stage, "metrics", {})
        if not isinstance(metrics, Mapping):
            continue

        raw_stage_name = getattr(stage, "name", None)
        if not isinstance(raw_stage_name, str):
            continue
        candidate = False

        for key, value in metrics.items():
            key_lower = str(key).lower()
            if not candidate and "cache" in key_lower:
                candidate = True
            if resim_count is None and "resim" in key_lower:
                try:
                    resim_count = int(value)
                except (TypeError, ValueError):
                    continue
            if avg_cache_gb is None and "cache" in key_lower and "gb" in key_lower:
                try:
                    avg_cache_gb = float(value)
                except (TypeError, ValueError):
                    continue

        if candidate and stage_name is None and isinstance(raw_stage_name, str):
            stage_name = raw_stage_name

    return stage_name, resim_count, avg_cache_gb


def _recommend_cache_rebuild_action(
    *,
    cache_stability: float,
    resim_count: int | None,
    avg_cache_gb: float | None,
    owners: Iterable[str],
) -> str:
    """Craft a remedial recommendation for unstable caches."""

    suggestions: list[str] = []

    if cache_stability < 0.6:
        suggestions.append(
            "Prioritise an immediate cache rebuild; stability is critical."
        )
    else:
        suggestions.append("Schedule a cache rebuild to stabilise downstream renders.")

    if resim_count is not None and resim_count > 0:
        suggestions.append(
            f"Coordinate with simulation after {resim_count} recent resim cycle(s)."
        )

    if avg_cache_gb is not None:
        suggestions.append(f"Provision roughly {avg_cache_gb:.1f}GB per cache pull.")

    owner_list = list(owners)
    if owner_list:
        suggestions.append(f"Loop in {owner_list[0]} to confirm handoff timing.")

    if not suggestions:
        return "Trigger cache rebuild and notify downstream departments."

    return " ".join(suggestions)


def _build_lifecycle_index(engine: Any) -> dict[tuple[str, str], Any]:
    lifecycles: Iterable[Any]
    lifecycle_index: dict[tuple[str, str], Any] = {}

    lifecycle_provider = getattr(engine, "shot_lifecycle", None)
    if callable(lifecycle_provider):
        lifecycles = lifecycle_provider()
    else:
        lifecycles = ()

    for lifecycle in lifecycles:
        key = (
            getattr(lifecycle, "sequence", None),
            getattr(lifecycle, "shot_id", None),
        )
        if None not in key:
            lifecycle_index[key] = lifecycle  # type: ignore[index]

    return lifecycle_index


def _extract_lifecycle_context(
    lifecycle: Any | None,
) -> tuple[tuple[str, ...], str | None]:
    if lifecycle is None:
        return (), None

    owners: list[str] = []
    stages = getattr(lifecycle, "stages", ())
    for stage in stages:
        metrics = getattr(stage, "metrics", {})
        if not isinstance(metrics, Mapping):
            continue
        for key, value in metrics.items():
            if not isinstance(value, str):
                continue
            key_lower = str(key).lower()
            if any(token in key_lower for token in _OWNER_KEYS) and value not in owners:
                owners.append(value)

    current_stage = getattr(lifecycle, "current_stage", None)
    return tuple(owners), current_stage if isinstance(current_stage, str) else None


def _collect_stage_owners(stage: Any) -> tuple[str, ...]:
    metrics = getattr(stage, "metrics", {})
    if not isinstance(metrics, Mapping):
        return ()

    owners: list[str] = []
    for key, value in metrics.items():
        if not isinstance(value, str):
            continue
        key_lower = str(key).lower()
        if any(token in key_lower for token in _OWNER_KEYS):
            owners.append(value)
    return tuple(owners)


def _run_rebuild_unstable_caches_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    indicators = list(engine.risk_heatmap())
    lifecycle_index = _build_lifecycle_index(engine)

    unstable: list[dict[str, Any]] = []
    for indicator in indicators:
        if indicator.cache_stability >= _CACHE_STABILITY_THRESHOLD:
            continue

        key = (indicator.sequence, indicator.shot_id)
        lifecycle = lifecycle_index.get(key)
        owners, current_stage = _extract_lifecycle_context(lifecycle)
        cache_stage, resim_count, avg_cache_gb = _extract_cache_metrics(lifecycle)

        recommendation = _recommend_cache_rebuild_action(
            cache_stability=indicator.cache_stability,
            resim_count=resim_count,
            avg_cache_gb=avg_cache_gb,
            owners=owners,
        )

        cache_metrics: dict[str, Any] = {}
        if resim_count is not None:
            cache_metrics["resim_count"] = resim_count
        if avg_cache_gb is not None:
            cache_metrics["avg_cache_gb"] = round(avg_cache_gb, 2)

        unstable.append(
            {
                "sequence": indicator.sequence,
                "shot": indicator.shot_id,
                "risk_score": indicator.risk_score,
                "cache_stability": round(indicator.cache_stability, 3),
                "cache_stability_percentage": round(indicator.cache_stability * 100, 1),
                "current_stage": current_stage,
                "owners": owners,
                "drivers": list(indicator.drivers),
                "cache_stage": cache_stage,
                "cache_metrics": cache_metrics,
                "recommendation": recommendation,
            }
        )

    unstable.sort(key=lambda item: item["cache_stability"])

    if unstable:
        worst = unstable[0]
        summary = (
            f"Rebuild caches for {len(unstable)} shot(s) under "
            f"{int(_CACHE_STABILITY_THRESHOLD * 100)}% stability — "
            f"{worst['sequence']} {worst['shot']} sits at {worst['cache_stability_percentage']:.1f}%."
        )
    else:
        summary = "Caches are stable — no rebuilds recommended right now."

    payload = {
        "summary": summary,
        "threshold": _CACHE_STABILITY_THRESHOLD,
        "total": len(unstable),
        "shots": unstable,
    }

    return WranglerScriptResult(
        script_id="rebuild_unstable_caches",
        status="success",
        message=summary,
        payload=payload,
    )


__all__ = [
    "_build_lifecycle_index",
    "_collect_stage_owners",
    "_extract_lifecycle_context",
    "_run_flag_render_error_streaks_script",
    "_run_rebuild_unstable_caches_script",
]
