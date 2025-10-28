"""Registry for operational Wrangler scripts exposed via the dashboard API."""

from __future__ import annotations

import asyncio
import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Iterable, Mapping, MutableMapping

from pydantic import BaseModel, Field

from apps.perona.web import dashboard as dashboard_module
from libraries.analytics.perona import engine as engine_module
from libraries.analytics.perona.engine import OptimizationScenario


class WranglerScriptMetadata(BaseModel):
    """Describes a Wrangler script surfaced by the dashboard."""

    script_id: str = Field(
        ..., pattern=r"^[A-Za-z0-9._-]+$", description="Stable identifier"
    )
    name: str
    description: str | None = None
    tags: tuple[str, ...] = ()


class WranglerScriptResult(BaseModel):
    """Structured result returned from executing a Wrangler script."""

    script_id: str
    status: str = Field(default="success", pattern=r"^(success|error)$")
    message: str | None = None
    payload: Any | None = None


AwaitableResult = (
    Awaitable[WranglerScriptResult | Mapping[str, Any] | None]
    | WranglerScriptResult
    | Mapping[str, Any]
    | None
)


@dataclass(slots=True)
class _RegisteredScript:
    metadata: WranglerScriptMetadata
    runner: Callable[[], AwaitableResult]


_scripts: MutableMapping[str, _RegisteredScript] = OrderedDict()


_TARGET_GPU_UTILISATION = 0.8
_UTILISATION_TOLERANCE = 0.05
_MIN_CONCURRENCY_RATIO = 0.25
_MAX_CONCURRENCY_RATIO = 1.75

_FAILING_RISK_THRESHOLD = 60.0
_FAILING_ERROR_THRESHOLD_MULTIPLIER = 1.5
_CACHE_STABILITY_THRESHOLD = 0.75
_OWNER_KEYS = ("owner", "artist", "lead", "supervisor", "producer", "coordinator")

_SPIN_DOWN_NOTES_PREFIX = (
    "Spin down idle workers to improve utilisation without starving the queue."
)


async def _coerce_result(
    script_id: str, result: WranglerScriptResult | Mapping[str, Any] | None
) -> WranglerScriptResult:
    if isinstance(result, WranglerScriptResult):
        if result.script_id != script_id:
            return result.model_copy(update={"script_id": script_id})
        return result

    payload: Mapping[str, Any] | None
    if result is None:
        payload = None
    else:
        payload = dict(result)

    status = "success"
    message = None
    if isinstance(payload, Mapping) and payload.get("status") in {"error", "success"}:
        status = str(payload.get("status"))
        message = (
            payload.get("message") if isinstance(payload.get("message"), str) else None
        )

    return WranglerScriptResult(
        script_id=script_id, status=status, message=message, payload=payload
    )


async def execute_script(script_id: str) -> WranglerScriptResult:
    registered = _scripts.get(script_id)
    if not registered:
        raise KeyError(script_id)

    try:
        outcome = registered.runner()
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
    except Exception as exc:  # pragma: no cover - defensive, surfaced via API tests
        return WranglerScriptResult(
            script_id=script_id, status="error", message=str(exc)
        )

    return await _coerce_result(script_id, outcome)  # type: ignore[arg-type]


def register_script(
    metadata: WranglerScriptMetadata, runner: Callable[[], AwaitableResult]
) -> None:
    if metadata.script_id in _scripts:
        raise ValueError(
            f"Wrangler script '{metadata.script_id}' is already registered"
        )
    _scripts[metadata.script_id] = _RegisteredScript(metadata=metadata, runner=runner)


def iter_registered_scripts() -> Iterable[WranglerScriptMetadata]:
    for entry in _scripts.values():
        yield entry.metadata


def get_registered_script(script_id: str) -> _RegisteredScript | None:
    return _scripts.get(script_id)


def _reset_registry() -> None:
    _scripts.clear()
    _register_builtin_scripts()


def _clamp(value: float, *, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _sequence_recommendations(
    summary: Mapping[str, Any], *, target: float
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    sequences = summary.get("sequences") or []
    for entry in sequences:
        sequence = entry.get("sequence")
        avg_utilisation = float(entry.get("avg_gpu_utilisation", 0.0) or 0.0)
        shots = int(entry.get("shots", 0) or 0)
        delta = avg_utilisation - target
        delta_pct = round(delta * 100, 1)
        utilisation_pct = round(avg_utilisation * 100, 1)

        if avg_utilisation < target - _UTILISATION_TOLERANCE:
            status = "under"
            recommendation = (
                "Under target — queue additional renders or reassign idle artists."
            )
        elif avg_utilisation > target + _UTILISATION_TOLERANCE:
            status = "over"
            recommendation = (
                "Above target — split workloads or request more GPU capacity."
            )
        else:
            status = "balanced"
            recommendation = "On track — maintain the current allocation."

        recommendations.append(
            {
                "sequence": sequence,
                "shots": shots,
                "average_utilisation": round(avg_utilisation, 3),
                "delta": round(delta, 3),
                "delta_percentage": delta_pct,
                "utilisation_percentage": utilisation_pct,
                "status": status,
                "recommendation": recommendation,
            }
        )

    recommendations.sort(key=lambda item: item["average_utilisation"])
    return recommendations


def _build_summary(
    summary: Mapping[str, Any],
    *,
    engine: Any,
    target: float,
    recommendations: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    averages = summary.get("averages") or {}
    average_utilisation = float(averages.get("gpu_utilisation", 0.0) or 0.0)
    delta = average_utilisation - target
    delta_pct = round(delta * 100, 1)
    utilisation_pct = round(average_utilisation * 100, 1)

    baseline_concurrency = getattr(
        getattr(engine, "baseline_cost_input", None), "gpu_count", None
    )
    recommended_concurrency: int | None = None
    if baseline_concurrency and target > 0:
        ratio = average_utilisation / target if target else 0.0
        ratio = _clamp(
            ratio, lower=_MIN_CONCURRENCY_RATIO, upper=_MAX_CONCURRENCY_RATIO
        )
        recommended_concurrency = max(1, round(baseline_concurrency * ratio))

    focus_sequences = [
        item["sequence"]
        for item in recommendations
        if item["status"] == "under" and item["sequence"]
    ][:3]
    focus_summary = ", ".join(str(name) for name in focus_sequences)

    if average_utilisation < target - _UTILISATION_TOLERANCE:
        status_text = "below"
    elif average_utilisation > target + _UTILISATION_TOLERANCE:
        status_text = "above"
    else:
        status_text = "on"

    parts = [
        (
            f"Average GPU utilisation is {utilisation_pct:.1f}% ({delta_pct:+.1f}pp vs "
            f"{target * 100:.1f}% target) and is {status_text} target."
        )
    ]

    if focus_summary:
        parts.append(f"Prioritise additional work for {focus_summary} to lift usage.")

    if (
        baseline_concurrency
        and recommended_concurrency
        and recommended_concurrency != baseline_concurrency
    ):
        if average_utilisation < target:
            parts.append(
                f"Consider scaling concurrency from {baseline_concurrency} to ~{recommended_concurrency} GPUs"
            )
        else:
            parts.append(
                f"Consider increasing concurrency towards ~{recommended_concurrency} GPUs"
            )

    summary_text = " ".join(parts)

    overall_payload = {
        "average_utilisation": round(average_utilisation, 3),
        "target_utilisation": target,
        "delta": round(delta, 3),
        "delta_percentage": delta_pct,
        "utilisation_percentage": utilisation_pct,
        "status": status_text,
        "total_samples": int(summary.get("total_samples", 0) or 0),
        "current_concurrency": baseline_concurrency,
        "recommended_concurrency": recommended_concurrency,
    }

    return summary_text, overall_payload


def _run_boost_gpu_utilisation_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    summary = dashboard_module.metrics_summary(engine=engine)

    recommendations = _sequence_recommendations(summary, target=_TARGET_GPU_UTILISATION)
    summary_text, overall_payload = _build_summary(
        summary,
        engine=engine,
        target=_TARGET_GPU_UTILISATION,
        recommendations=recommendations,
    )

    payload = {
        "summary": summary_text,
        "overall": overall_payload,
        "sequences": recommendations,
    }

    return WranglerScriptResult(
        script_id="boost_gpu_utilisation",
        status="success",
        message=summary_text,
        payload=payload,
    )


def _run_analyse_cost_drivers_script() -> WranglerScriptResult:
    """Summarise the leading cost drivers and proposed remediations."""

    engine = dashboard_module.get_engine()
    statistics, recommendations = engine.cost_insights(top_n=5)

    recommended_actions = list(recommendations)

    if not statistics:
        message = (
            "Cost driver insights are unavailable; ingest telemetry before retrying."
        )
        return WranglerScriptResult(
            script_id="analyse_cost_drivers",
            status="error",
            message=message,
            payload={
                "headline": message,
                "top_features": [],
                "recommended_actions": recommended_actions,
            },
        )

    def _feature_delta(entry: Any) -> float:
        try:
            return float(entry.maximum) - float(entry.minimum)
        except Exception:  # pragma: no cover - defensive fallback
            return 0.0

    sorted_stats = sorted(statistics, key=_feature_delta, reverse=True)
    top_features: list[dict[str, Any]] = []
    for entry in sorted_stats[:5]:
        delta = _feature_delta(entry)
        top_features.append(
            {
                "feature": getattr(entry, "name", None),
                "mean": round(float(getattr(entry, "mean", 0.0) or 0.0), 3),
                "stddev": round(float(getattr(entry, "stddev", 0.0) or 0.0), 3),
                "minimum": round(float(getattr(entry, "minimum", 0.0) or 0.0), 3),
                "maximum": round(float(getattr(entry, "maximum", 0.0) or 0.0), 3),
                "delta": round(delta, 3),
            }
        )

    leader = top_features[0]
    headline = (
        f"{leader['feature']} spans {leader['delta']:.3f} between observed min/max "
        "cost inputs — address the top drivers to stabilise spend."
    )

    payload = {
        "headline": headline,
        "top_features": top_features,
        "recommended_actions": recommended_actions,
    }

    return WranglerScriptResult(
        script_id="analyse_cost_drivers",
        status="success",
        message=headline,
        payload=payload,
    )


def _run_explain_pnl_delta_script() -> WranglerScriptResult:
    """Summarise how current render spend deviates from the baseline."""

    engine = dashboard_module.get_engine()
    baseline_input = getattr(engine, "baseline_cost_input", None)
    if baseline_input is None:
        message = (
            "Baseline cost input unavailable; configure Perona settings before "
            "explaining the P&L delta."
        )
        return WranglerScriptResult(
            script_id="explain_pnl_delta",
            status="error",
            message=message,
            payload=None,
        )

    breakdown = engine.pnl_explainer()
    baseline_breakdown = engine.estimate_cost(baseline_input)

    frame_count = max(getattr(baseline_breakdown, "frame_count", 0) or 0, 1)
    baseline_total = round(float(baseline_breakdown.total_cost), 2)
    current_total = round(float(breakdown.current_cost), 2)
    delta_total = round(float(breakdown.delta_cost), 2)
    currency = getattr(baseline_breakdown, "currency", None)

    baseline_cost_per_frame = round(float(baseline_breakdown.cost_per_frame), 4)
    current_cost_per_frame = round(current_total / frame_count, 4)
    delta_cost_per_frame = round(current_cost_per_frame - baseline_cost_per_frame, 4)

    contributions = sorted(
        getattr(breakdown, "contributions", ()),
        key=lambda item: abs(getattr(item, "delta_cost", 0.0)),
        reverse=True,
    )

    ranked_contributions: list[dict[str, Any]] = []
    for index, contribution in enumerate(contributions[:3], start=1):
        ranked_contributions.append(
            {
                "rank": index,
                "factor": getattr(contribution, "factor", None),
                "delta_cost": round(float(getattr(contribution, "delta_cost", 0.0)), 2),
                "percentage_points": round(
                    float(getattr(contribution, "percentage_points", 0.0)), 2
                ),
                "narrative": getattr(contribution, "narrative", None),
            }
        )

    formatted_delta = f"{delta_total:+.2f}"
    formatted_leader_delta: str | None = None
    if currency:
        formatted_delta = f"{currency} {formatted_delta}"

    if ranked_contributions:
        leader = ranked_contributions[0]
        formatted_leader_delta = f"{leader['delta_cost']:+.2f}"
        if currency:
            formatted_leader_delta = f"{currency} {formatted_leader_delta}"
        message = (
            "Render spend delta "
            f"{formatted_delta} vs baseline; leading factor: {leader['factor']}"
        )
        if formatted_leader_delta is not None:
            message += f" ({formatted_leader_delta})."
        else:
            message += "."
    else:
        message = (
            f"Render spend delta {formatted_delta} vs baseline; "
            "no contribution data available."
        )

    payload = {
        "totals": {
            "baseline": baseline_total,
            "current": current_total,
            "delta": delta_total,
            "currency": currency,
        },
        "per_frame": {
            "baseline": baseline_cost_per_frame,
            "current": current_cost_per_frame,
            "delta": delta_cost_per_frame,
        },
        "frame_count": frame_count,
        "contributions": ranked_contributions,
    }

    return WranglerScriptResult(
        script_id="explain_pnl_delta",
        status="success",
        message=message,
        payload=payload,
    )


def _resolve_baseline_concurrency(engine: Any) -> int | None:
    baseline = getattr(engine, "baseline_cost_input", None)
    gpu_count = getattr(baseline, "gpu_count", None)
    if isinstance(gpu_count, (int, float)):
        resolved = int(gpu_count)
        if resolved > 0:
            return resolved
    return None


def _project_utilisation(current: float, *, baseline: int, proposed: int) -> float:
    if proposed <= 0 or baseline <= 0:
        return current
    projected = current * (baseline / proposed)
    return _clamp(projected, lower=0.0, upper=1.0)


def _run_spin_down_idle_workers_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    summary = dashboard_module.metrics_summary(engine=engine)

    averages = summary.get("averages") or {}
    average_utilisation = float(averages.get("gpu_utilisation", 0.0) or 0.0)
    baseline_concurrency = _resolve_baseline_concurrency(engine)

    target = _TARGET_GPU_UTILISATION
    tolerance = _UTILISATION_TOLERANCE
    band_lower = max(0.0, target - tolerance)
    band_upper = min(1.0, target + tolerance)

    if baseline_concurrency is None:
        message = (
            "Unable to determine the baseline GPU worker count; update Perona settings."
        )
        payload = {
            "current_utilisation": round(average_utilisation, 3),
            "baseline_worker_count": None,
            "recommended_worker_count": None,
            "target_band": {"lower": band_lower, "upper": band_upper},
            "projected_utilisation": None,
            "projected_savings": None,
            "notes": [
                "Baseline GPU configuration is missing, preventing a spin down recommendation.",
            ],
        }
        return WranglerScriptResult(
            script_id="spin_down_idle_workers",
            status="error",
            message=message,
            payload=payload,
        )

    notes: list[str] = []
    projected_savings: Mapping[str, Any] | None = None
    recommended_concurrency = baseline_concurrency

    if average_utilisation < band_lower:
        ratio = average_utilisation / target if target else 0.0
        ratio = _clamp(ratio, lower=_MIN_CONCURRENCY_RATIO, upper=1.0)
        recommended_concurrency = max(1, int(baseline_concurrency * ratio))
        if recommended_concurrency >= baseline_concurrency and baseline_concurrency > 1:
            recommended_concurrency = baseline_concurrency - 1

        projected_utilisation = _project_utilisation(
            average_utilisation,
            baseline=baseline_concurrency,
            proposed=recommended_concurrency,
        )
        notes.append(
            f"Projected utilisation after change: {projected_utilisation * 100:.1f}%"
        )
        if projected_utilisation > band_upper:
            notes.append(
                "Utilisation may briefly exceed the target band; monitor queue depth after scaling."
            )

        if recommended_concurrency < baseline_concurrency:
            scenario = OptimizationScenario(
                name=f"Scale to {recommended_concurrency} GPUs",
                gpu_count=recommended_concurrency,
                notes=_SPIN_DOWN_NOTES_PREFIX,
            )
            try:
                baseline_breakdown, results = engine.run_optimization_backtest(
                    [scenario]
                )
            except Exception as exc:  # pragma: no cover - defensive
                notes.append(f"Cost optimisation backtest failed: {exc}")
            else:
                if results:
                    result = results[0]
                    projected_savings = {
                        "amount": round(result.savings_vs_baseline, 2),
                        "percentage": round(result.savings_percent, 2),
                        "currency": getattr(baseline_breakdown, "currency", None),
                        "baseline_cost": round(baseline_breakdown.total_cost, 2),
                        "projected_cost": round(result.total_cost, 2),
                    }
                    if result.savings_vs_baseline <= 0:
                        notes.append(
                            "Backtest indicates limited savings; validate before committing to the change."
                        )
        else:
            projected_utilisation = average_utilisation
    else:
        projected_utilisation = average_utilisation
        notes.append(
            "Utilisation already sits within the target band; retain the current GPU allocation."
        )

    utilisation_pct = average_utilisation * 100
    lower_pct = band_lower * 100
    upper_pct = band_upper * 100

    if recommended_concurrency < baseline_concurrency:
        message = (
            f"GPU utilisation is {utilisation_pct:.1f}% — below the {lower_pct:.0f}-{upper_pct:.0f}% "
            f"target band. Recommend scaling workers from {baseline_concurrency} to "
            f"{recommended_concurrency}."
        )
    else:
        message = (
            f"GPU utilisation is {utilisation_pct:.1f}% and within the {lower_pct:.0f}-{upper_pct:.0f}% "
            "target band. No spin down recommended."
        )

    payload = {
        "current_utilisation": round(average_utilisation, 3),
        "baseline_worker_count": baseline_concurrency,
        "recommended_worker_count": recommended_concurrency,
        "target_band": {"lower": round(band_lower, 3), "upper": round(band_upper, 3)},
        "projected_utilisation": round(projected_utilisation, 3),
        "projected_savings": projected_savings,  # type: ignore[dict-item]
        "total_samples": int(summary.get("total_samples", 0) or 0),
        "notes": notes or [_SPIN_DOWN_NOTES_PREFIX],
    }

    return WranglerScriptResult(
        script_id="spin_down_idle_workers",
        status="success",
        message=message,
        payload=payload,
    )


def _derive_follow_up(drivers: Iterable[str]) -> str:
    """Suggest the next action based on risk drivers."""

    for driver in drivers:
        if "Error rate high" in driver:
            return "Escalate to QA to diagnose and reduce error spikes."
        if "Deadline missed" in driver:
            return "Coordinate recovery plan with production to unblock delivery."
        if "Deadline pressure" in driver:
            return "Reallocate render capacity to beat the approaching deadline."
        if "Render time volatility" in driver:
            return "Profile recent renders to stabilise frame times."
        if "Cache rebuild risk" in driver:
            return "Trigger cache rebuild and validate downstream dependencies."

    return "Monitor the shot and re-evaluate after the next render cycle."


def _run_list_failing_jobs_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    indicators = list(engine.risk_heatmap())

    target_error_rate = getattr(engine, "target_error_rate", 0.0) or 0.0
    error_threshold = max(target_error_rate * _FAILING_ERROR_THRESHOLD_MULTIPLIER, 0.01)

    failing: list[dict[str, Any]] = []
    for indicator in indicators:
        drivers = list(indicator.drivers)
        include = (
            indicator.risk_score >= _FAILING_RISK_THRESHOLD
            or indicator.error_rate >= error_threshold
            or any("Error rate high" in driver for driver in drivers)
        )
        if not include:
            continue

        failing.append(
            {
                "sequence": indicator.sequence,
                "shot": indicator.shot_id,
                "risk_score": indicator.risk_score,
                "error_rate": indicator.error_rate,
                "drivers": drivers,
                "recommended_follow_up": _derive_follow_up(drivers),
            }
        )

    failing.sort(key=lambda item: item["risk_score"], reverse=True)

    if failing:
        top = failing[0]
        headline = (
            f"{len(failing)} critical shot(s) flagged — "
            f"{top['sequence']} {top['shot']} tops the risk board at {top['risk_score']:.1f}."
        )
    else:
        headline = "No shots are currently breaching risk or error thresholds."

    payload = {"headline": headline, "details": failing}

    return WranglerScriptResult(
        script_id="list_failing_jobs",
        status="success",
        message=headline,
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
        candidate = False
        if isinstance(raw_stage_name, str):
            candidate = raw_stage_name.lower() in {"sim", "simulation", "caches"}

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


def _deadline_horizon_from_hours(hours: float | None) -> str | None:
    if hours is None:
        return None
    if hours <= 0:
        return "Past due"

    remaining = math.ceil(hours)
    if remaining < 24:
        return f"Due in {remaining}h"

    days, rem_hours = divmod(remaining, 24)
    if rem_hours:
        return f"Due in {days}d {rem_hours}h"
    return f"Due in {days}d"


def _infer_deadline_horizon(drivers: Iterable[str]) -> str | None:
    for driver in drivers:
        lower = driver.lower()
        if "deadline missed" in lower:
            return "Past due"
        if "deadline pressure" in lower:
            match = re.search(r"([0-9]+(?:\.[0-9]+)?)h", driver)
            if match:
                try:
                    hours = float(match.group(1))
                except ValueError:
                    continue
                return _deadline_horizon_from_hours(hours)
    return None


def _build_telemetry_index(engine: Any) -> dict[tuple[str, str], Any]:
    telemetry_index: dict[tuple[str, str], Any] = {}
    telemetry = getattr(engine, "_telemetry", ())
    for sample in telemetry:
        key = (getattr(sample, "sequence", None), getattr(sample, "shot_id", None))
        if None not in key:
            telemetry_index[key] = sample  # type: ignore[index]
    return telemetry_index


def _resolve_deadline_horizon(
    telemetry_sample: Any | None, drivers: Iterable[str]
) -> str | None:
    deadline: datetime | None = getattr(telemetry_sample, "deadline", None)
    if isinstance(deadline, datetime):
        reference: datetime | None = getattr(
            engine_module, "_RISK_REFERENCE_TIME", None
        )
        if isinstance(reference, datetime):
            hours = (deadline - reference).total_seconds() / 3600.0
        else:
            hours = (deadline - datetime.utcnow()).total_seconds() / 3600.0
        return _deadline_horizon_from_hours(hours)

    return _infer_deadline_horizon(drivers)


def _run_escalate_deadline_shots_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    indicators = list(engine.risk_heatmap())
    lifecycle_index = _build_lifecycle_index(engine)
    telemetry_index = _build_telemetry_index(engine)

    escalations: list[dict[str, Any]] = []
    for indicator in indicators:
        drivers = [
            driver for driver in indicator.drivers if "deadline" in driver.lower()
        ]
        if not drivers:
            continue

        key = (indicator.sequence, indicator.shot_id)
        lifecycle = lifecycle_index.get(key)
        owners, current_stage = _extract_lifecycle_context(lifecycle)
        telemetry_sample = telemetry_index.get(key)
        deadline_horizon = _resolve_deadline_horizon(telemetry_sample, drivers)

        escalations.append(
            {
                "sequence": indicator.sequence,
                "shot": indicator.shot_id,
                "risk_score": indicator.risk_score,
                "current_stage": current_stage,
                "deadline_horizon": deadline_horizon,
                "owners": owners,
                "drivers": drivers,
            }
        )

    escalations.sort(key=lambda item: item["risk_score"], reverse=True)

    if escalations:
        headline = (
            f"{len(escalations)} shot(s) breaching deadline risk — "
            f"{escalations[0]['sequence']} {escalations[0]['shot']} leads the queue."
        )
    else:
        headline = "No shots currently require deadline escalation."

    payload = {
        "summary": headline,
        "total": len(escalations),
        "escalations": escalations,
    }

    return WranglerScriptResult(
        script_id="escalate_deadline_shots",
        status="success",
        message=headline,
        payload=payload,
    )


def _register_builtin_scripts() -> None:
    if "analyse_cost_drivers" not in _scripts:
        register_script(
            WranglerScriptMetadata(
                script_id="analyse_cost_drivers",
                name="Analyse cost drivers",
                description="Highlight the strongest cost inputs and optimisation levers",
                tags=("cost", "insights", "telemetry"),
            ),
            _run_analyse_cost_drivers_script,
        )
    if "explain_pnl_delta" not in _scripts:
        register_script(
            WranglerScriptMetadata(
                script_id="explain_pnl_delta",
                name="Explain P&L delta",
                description=(
                    "Contrast baseline vs current render spend and rank the delta drivers"
                ),
                tags=("finance", "pnl", "insights"),
            ),
            _run_explain_pnl_delta_script,
        )
    if "boost_gpu_utilisation" not in _scripts:
        register_script(
            WranglerScriptMetadata(
                script_id="boost_gpu_utilisation",
                name="Boost GPU utilisation",
                description="Analyse render telemetry to lift GPU usage",
                tags=("rendering", "utilisation"),
            ),
            _run_boost_gpu_utilisation_script,
        )
    if "spin_down_idle_workers" not in _scripts:
        register_script(
            WranglerScriptMetadata(
                script_id="spin_down_idle_workers",
                name="Spin down idle GPU workers",
                description=(
                    "Recommend reducing GPU nodes when utilisation drops below the target band"
                ),
                tags=("rendering", "capacity", "cost"),
            ),
            _run_spin_down_idle_workers_script,
        )
    if "list_failing_jobs" not in _scripts:
        register_script(
            WranglerScriptMetadata(
                script_id="list_failing_jobs",
                name="List failing jobs",
                description="Surface critical shots breaching risk thresholds",
                tags=("risk", "shots"),
            ),
            _run_list_failing_jobs_script,
        )
    if "rebuild_unstable_caches" not in _scripts:
        register_script(
            WranglerScriptMetadata(
                script_id="rebuild_unstable_caches",
                name="Rebuild unstable caches",
                description="Target shots with low cache stability and propose remedial actions",
                tags=("risk", "caches", "simulation"),
            ),
            _run_rebuild_unstable_caches_script,
        )
    if "escalate_deadline_shots" not in _scripts:
        register_script(
            WranglerScriptMetadata(
                script_id="escalate_deadline_shots",
                name="Escalate deadline-sensitive shots",
                description=(
                    "Highlight shots with deadline pressure and propose production follow-up"
                ),
                tags=("risk", "shots", "deadline"),
            ),
            _run_escalate_deadline_shots_script,
        )


_register_builtin_scripts()
