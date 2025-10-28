"""Registry for operational Wrangler scripts exposed via the dashboard API."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Mapping, MutableMapping

from pydantic import BaseModel, Field

from apps.perona.web import dashboard as dashboard_module
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


def _resolve_baseline_concurrency(engine: Any) -> int | None:
    baseline = getattr(engine, "baseline_cost_input", None)
    gpu_count = getattr(baseline, "gpu_count", None)
    if isinstance(gpu_count, (int, float)):
        resolved = int(gpu_count)
        if resolved > 0:
            return resolved
    return None


def _project_utilisation(
    current: float, *, baseline: int, proposed: int
) -> float:
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
            average_utilisation, baseline=baseline_concurrency, proposed=recommended_concurrency
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
                baseline_breakdown, results = engine.run_optimization_backtest([scenario])
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
        "projected_savings": projected_savings,
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


def _register_builtin_scripts() -> None:
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


_register_builtin_scripts()
