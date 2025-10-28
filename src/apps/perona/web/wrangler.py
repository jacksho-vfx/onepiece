"""Registry for operational Wrangler scripts exposed via the dashboard API."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Mapping, MutableMapping

from pydantic import BaseModel, Field

from apps.perona.web import dashboard as dashboard_module


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


_register_builtin_scripts()
