"""Wrangler scripts focused on production operations and risk."""

from __future__ import annotations

import math
import re
import statistics
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from apps.perona.web import dashboard as dashboard_module
from libraries.analytics.perona import engine as engine_module

from ..registry import WranglerScriptResult
from .ops import _run_spin_down_idle_workers_script
from .risk import (
    _build_lifecycle_index,
    _collect_stage_owners,
    _extract_lifecycle_context,
    _run_flag_render_error_streaks_script,
    _run_rebuild_unstable_caches_script,
)
from .telemetry import _build_telemetry_index

_FAILING_RISK_THRESHOLD = 60.0
_FAILING_ERROR_THRESHOLD_MULTIPLIER = 1.5
_DEFAULT_FRAME_TIME_REGRESSION_THRESHOLD = 0.1

_STAGE_FOLLOW_UP = {
    "layout": "assign layout owner",
    "sim": "assign sim lead",
    "simulation": "assign sim lead",
    "lighting": "assign lighting artist",
    "light": "assign lighting artist",
    "comp": "assign comp lead",
    "compositing": "assign comp lead",
    "fx": "assign fx supervisor",
}


def _derive_follow_up(drivers: Iterable[str]) -> str:
    """Suggest the next action based on risk drivers."""

    for driver in drivers:
        if "Deadline" in driver:
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


def _build_render_volatility_report(
    engine: Any,
) -> tuple[str, list[dict[str, Any]]]:
    indicators = list(engine.risk_heatmap())
    frame_time_index = getattr(engine, "_frame_times_by_shot", {})

    hotspots: list[dict[str, Any]] = []
    for indicator in indicators:
        drivers = list(indicator.drivers)
        if not any("Render time volatility" in driver for driver in drivers):
            continue

        frames = ()
        if isinstance(frame_time_index, Mapping):
            frames = frame_time_index.get(
                (indicator.sequence, indicator.shot_id),
                (),
            )

        sample_count = len(frames)
        if sample_count:
            average_ms = statistics.fmean(frames)
            stddev_ms = statistics.pstdev(frames) if sample_count > 1 else 0.0
        else:
            average_ms = float(indicator.render_time_ms or 0.0)
            stddev_ms = 0.0

        coefficient = (stddev_ms / average_ms) if average_ms else 0.0

        hotspots.append(
            {
                "sequence": indicator.sequence,
                "shot": indicator.shot_id,
                "risk_score": indicator.risk_score,
                "render_time_ms": round(indicator.render_time_ms, 3),
                "variance": {
                    "sample_count": sample_count,
                    "average_frame_time_ms": round(average_ms, 3),
                    "stddev_frame_time_ms": round(stddev_ms, 3),
                    "coefficient_of_variation": round(coefficient, 4),
                },
                "drivers": drivers,
                "recommended_follow_up": _derive_follow_up(drivers),
            }
        )

    hotspots.sort(key=lambda item: item["risk_score"], reverse=True)

    if hotspots:
        leader = hotspots[0]
        headline = (
            f"{len(hotspots)} volatility hotspot(s) — "
            f"{leader['sequence']} {leader['shot']} leads at risk {leader['risk_score']:.1f}."
        )
    else:
        headline = "Frame times steady — no volatility hotspots detected."

    return headline, hotspots


def _run_flag_render_volatility_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    headline, hotspots = _build_render_volatility_report(engine)

    payload = {"headline": headline, "volatility": hotspots}

    return WranglerScriptResult(
        script_id="flag_render_volatility",
        status="success",
        message=headline,
        payload=payload,
    )


def _resolve_frame_time_regression_threshold(engine: Any, baseline: Any) -> float:
    """Return the configured frame time regression threshold as a ratio."""

    candidates = (
        getattr(engine, "frame_time_regression_threshold", None),
        getattr(baseline, "frame_time_regression_threshold", None),
    )

    for candidate in candidates:
        if candidate is None:
            continue
        try:
            value = float(candidate)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            continue
        if value > 0:
            return value

    return _DEFAULT_FRAME_TIME_REGRESSION_THRESHOLD


def _regression_mitigation(utilisation: float, delta_ratio: float) -> str:
    utilisation_pct = utilisation * 100

    if utilisation_pct >= 85:
        return (
            "Split heavy renders across more GPUs or reschedule to relieve contention."
        )
    if utilisation_pct <= 45:
        return "Inspect simulation and cache performance before re-queuing renders."
    if delta_ratio >= 0.25:
        return "Escalate to profiling to trim shading and lighting hot spots."
    return "Profile recent renders and tighten scene optimisations to recover baseline."


def _utilisation_context(utilisation: float) -> str:
    utilisation_pct = utilisation * 100
    if utilisation_pct >= 85:
        return f"High GPU load (~{utilisation_pct:.1f}%)"
    if utilisation_pct >= 60:
        return f"Moderate GPU load (~{utilisation_pct:.1f}%)"
    return f"Low GPU load (~{utilisation_pct:.1f}%)"


def _run_flag_frame_time_regressions_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    baseline_input = getattr(engine, "baseline_cost_input", None)

    baseline_frame_time: float | None = None
    if baseline_input is not None:
        candidate = getattr(baseline_input, "average_frame_time_ms", None)
        try:
            baseline_frame_time = float(candidate)  # type: ignore[arg-type]
        except (TypeError, ValueError):  # pragma: no cover - defensive
            baseline_frame_time = None

    summary = dashboard_module.metrics_summary(engine=engine)

    payload: dict[str, Any] = {
        "summary": None,
        "baseline_frame_time_ms": (
            None if baseline_frame_time is None else round(baseline_frame_time, 3)
        ),
        "threshold_percentage": None,
        "total_sequences": len(summary.get("sequences") or []),
        "regression_count": 0,
        "regressions": [],
    }

    if baseline_frame_time is None or baseline_frame_time <= 0:
        message = "Baseline average frame time unavailable; configure Perona cost inputs first."
        payload["summary"] = message
        return WranglerScriptResult(
            script_id="flag_frame_time_regressions",
            status="error",
            message=message,
            payload=payload,
        )

    threshold_ratio = _resolve_frame_time_regression_threshold(engine, baseline_input)
    payload["threshold_percentage"] = round(threshold_ratio * 100, 1)

    sequences = summary.get("sequences") or []

    regressions: list[dict[str, Any]] = []
    for entry in sequences:
        avg_frame_time = entry.get("avg_frame_time_ms")
        if avg_frame_time is None:
            continue
        try:
            avg_frame_time = float(avg_frame_time)
        except (TypeError, ValueError):
            continue

        delta_ratio = (avg_frame_time - baseline_frame_time) / baseline_frame_time
        if delta_ratio <= threshold_ratio:
            continue

        avg_gpu_utilisation = entry.get("avg_gpu_utilisation") or 0.0
        try:
            avg_gpu_utilisation = float(avg_gpu_utilisation)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            avg_gpu_utilisation = 0.0

        regression = {
            "sequence": entry.get("sequence"),
            "avg_frame_time_ms": round(avg_frame_time, 3),
            "delta_percentage": round(delta_ratio * 100, 1),
            "avg_gpu_utilisation": round(avg_gpu_utilisation, 3),
            "gpu_utilisation_percentage": round(avg_gpu_utilisation * 100, 1),
            "utilisation_context": _utilisation_context(avg_gpu_utilisation),
            "recommendation": _regression_mitigation(avg_gpu_utilisation, delta_ratio),
        }

        regressions.append(regression)

    regressions.sort(key=lambda item: item["delta_percentage"], reverse=True)

    payload.update(
        {
            "regression_count": len(regressions),
            "regressions": regressions,
        }
    )

    if regressions:
        worst = regressions[0]
        message = (
            "Frame time regressions detected — "
            f"{worst.get('sequence')} averaging {worst['avg_frame_time_ms']:.1f}ms "
            f"({worst['delta_percentage']:+.1f}% vs {baseline_frame_time:.1f}ms baseline)."
        )
    else:
        message = (
            "Frame times healthy — all sequences within "
            f"{payload['threshold_percentage']:.1f}% of {baseline_frame_time:.1f}ms baseline."
        )

    payload["summary"] = message

    return WranglerScriptResult(
        script_id="flag_frame_time_regressions",
        status="success",
        message=message,
        payload=payload,
    )


def _normalise_stage_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _suggest_stage_follow_up(stage_name: str | None) -> str:
    if not stage_name:
        return "assign owner"

    key = stage_name.lower()
    suggestion = _STAGE_FOLLOW_UP.get(key)
    if suggestion:
        return suggestion
    if key.endswith("ing"):
        return f"assign {key} lead"
    return f"assign {key} owner"


def _identify_current_stage(
    lifecycle: Any, name_hint: str | None
) -> tuple[Any | None, str | None]:
    stages = getattr(lifecycle, "stages", ())
    matched_stage: Any | None = None
    resolved_name = name_hint

    if isinstance(resolved_name, str):
        for stage in stages:
            stage_name = getattr(stage, "name", None)
            if (
                isinstance(stage_name, str)
                and stage_name.lower() == resolved_name.lower()
            ):
                matched_stage = stage
                resolved_name = stage_name
                break

    if matched_stage is None:
        for stage in stages:
            completed = getattr(stage, "completed_at", None)
            if completed is None:
                matched_stage = stage
                stage_name = getattr(stage, "name", None)
                if isinstance(stage_name, str):
                    resolved_name = stage_name
                break

    if not isinstance(resolved_name, str):
        resolved_name = None

    return matched_stage, resolved_name


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
            match = re.search(r"([0-9]+(?:\\.[0-9]+)?)h", driver)
            if match:
                try:
                    hours = float(match.group(1))
                except ValueError:
                    continue
                return _deadline_horizon_from_hours(hours)
    return None


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


def _run_identify_unowned_shots_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    lifecycle_provider = getattr(engine, "shot_lifecycle", None)
    if callable(lifecycle_provider):
        lifecycles = lifecycle_provider()
    else:
        lifecycles = ()

    missing_assignments: list[tuple[float, dict[str, Any]]] = []

    for lifecycle in lifecycles:
        _owners, current_stage_name = _extract_lifecycle_context(lifecycle)
        stage, resolved_stage_name = _identify_current_stage(
            lifecycle, current_stage_name
        )
        if stage is None:
            continue

        if getattr(stage, "completed_at", None) is not None:
            continue

        stage_owners = _collect_stage_owners(stage)
        if stage_owners:
            continue

        sequence = getattr(lifecycle, "sequence", None)
        shot_id = getattr(lifecycle, "shot_id", None)

        if not isinstance(sequence, str):
            sequence = str(sequence) if sequence is not None else "Unknown"
        if not isinstance(shot_id, str):
            shot_id = str(shot_id) if shot_id is not None else "Unknown"

        stage_started = _normalise_stage_timestamp(getattr(stage, "started_at", None))
        stage_started_iso = stage_started.isoformat() if stage_started else None
        current_stage = resolved_stage_name or current_stage_name or "Unknown"
        suggestion = _suggest_stage_follow_up(
            current_stage if isinstance(current_stage, str) else None
        )

        entry = {
            "sequence": sequence,
            "shot": shot_id,
            "current_stage": current_stage,
            "stage_started_at": stage_started_iso,
            "suggested_follow_up": suggestion,
        }

        sort_key = stage_started.timestamp() if stage_started else float("inf")
        missing_assignments.append((sort_key, entry))

    missing_assignments.sort(key=lambda item: item[0])
    unassigned_shots = [entry for _, entry in missing_assignments]

    if unassigned_shots:
        focus = unassigned_shots[0]
        stage_fragment = (
            f" ({focus['current_stage']})"
            if isinstance(focus.get("current_stage"), str) and focus["current_stage"]
            else ""
        )
        message = (
            f"{len(unassigned_shots)} active shot(s) missing assignments — focus on "
            f"{focus['sequence']} {focus['shot']}{stage_fragment}."
        )
    else:
        message = "All active shots have current stage owners."

    payload = {
        "summary": message,
        "total_unassigned": len(unassigned_shots),
        "shots": unassigned_shots,
    }

    return WranglerScriptResult(
        script_id="identify_unowned_shots",
        status="success",
        message=message,
        payload=payload,
    )


def _parse_datetime(value: Any) -> datetime | None:
    """Return a :class:`datetime` for ``value`` when possible."""

    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        candidate = value
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            return None
    return None


def _format_duration(hours: float | None) -> str | None:
    if hours is None:
        return None
    if hours >= 48:
        return f"~{hours / 24:.1f} days"
    if hours >= 1:
        return f"~{hours:.1f} hours"
    return "<1 hour"


def _run_highlight_stage_bottlenecks_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    summary = dashboard_module.shots_summary(
        sequence=None,
        artist=None,
        start_date=None,
        end_date=None,
        engine=engine,
    )

    by_stage = summary.get("by_stage") or []
    stage_counts: list[dict[str, Any]] = []
    for entry in by_stage:
        name = entry.get("name")
        shots = entry.get("shots")
        if not isinstance(name, str):
            name = str(name) if name is not None else "Unknown"
        try:
            count = int(shots)
        except (TypeError, ValueError):
            count = 0
        stage_counts.append({"name": name, "shots": count})

    stage_counts.sort(key=lambda item: item["shots"], reverse=True)

    busiest_stage = stage_counts[0] if stage_counts else None
    busiest_stage_name = busiest_stage["name"] if busiest_stage else None

    active_shots_raw = summary.get("active_shots") or []
    parsed_shots: list[dict[str, Any]] = []
    now_utc = datetime.now(timezone.utc)

    for shot in active_shots_raw:
        sequence = shot.get("sequence")
        shot_id = shot.get("shot_id")
        current_stage = shot.get("current_stage")
        stage_started_at = _parse_datetime(shot.get("stage_started_at"))

        if not isinstance(sequence, str):
            sequence = str(sequence) if sequence is not None else "Unknown"
        if not isinstance(shot_id, str):
            shot_id = str(shot_id) if shot_id is not None else "Unknown"
        if not isinstance(current_stage, str):
            current_stage = (
                str(current_stage) if current_stage is not None else "Unknown"
            )

        elapsed_hours: float | None = None
        iso_started_at: str | None = None
        if stage_started_at is not None:
            reference_start = stage_started_at
            if reference_start.tzinfo is None:
                reference_start = reference_start.replace(tzinfo=timezone.utc)
            elapsed = now_utc - reference_start.astimezone(timezone.utc)
            elapsed_hours = max(elapsed.total_seconds(), 0.0) / 3600.0
            iso_started_at = reference_start.astimezone(timezone.utc).isoformat()

        parsed_shots.append(
            {
                "sequence": sequence,
                "shot": shot_id,
                "current_stage": current_stage,
                "stage_started_at": iso_started_at,
                "elapsed_hours": elapsed_hours,
            }
        )

    parsed_shots.sort(
        key=lambda item: (
            item["elapsed_hours"] if item["elapsed_hours"] is not None else -1.0
        ),
        reverse=True,
    )

    if busiest_stage_name:
        worst_offenders = [
            item for item in parsed_shots if item["current_stage"] == busiest_stage_name
        ]
        if not worst_offenders:
            worst_offenders = parsed_shots
    else:
        worst_offenders = parsed_shots

    worst_offenders = worst_offenders[:5]

    message: str
    if busiest_stage and busiest_stage["shots"] > 0:
        top_offender = worst_offenders[0] if worst_offenders else None
        duration_text = _format_duration(
            top_offender.get("elapsed_hours") if top_offender else None
        )
        if top_offender and duration_text:
            message = (
                f"{busiest_stage_name} is the busiest stage with "
                f"{busiest_stage['shots']} active shot(s); focus on {top_offender['sequence']} "
                f"{top_offender['shot']} {duration_text} in stage."
            )
        else:
            message = (
                f"{busiest_stage_name} is the busiest stage with "
                f"{busiest_stage['shots']} active shot(s)."
            )
    else:
        message = "No active stage bottlenecks detected — all stages are clear."

    next_steps: list[str] = []
    if busiest_stage and busiest_stage["shots"] > 0:
        next_steps.append(
            f"Assign extra capacity to {busiest_stage_name} to relieve the backlog."
        )
        if worst_offenders:
            offenders_list = ", ".join(
                f"{item['sequence']} {item['shot']}" for item in worst_offenders[:3]
            )
            next_steps.append(f"Review blockers for stalled shots: {offenders_list}.")
        next_steps.append(
            "Confirm downstream teams are aware of incoming handoffs once cleared."
        )
    else:
        next_steps.append(
            "Continue monitoring workloads; no immediate action required."
        )

    payload = {
        "summary": message,
        "per_stage_counts": stage_counts,
        "worst_offenders": [
            {
                **item,
                "elapsed_hours": (
                    round(item["elapsed_hours"], 2)
                    if item["elapsed_hours"] is not None
                    else None
                ),
                "elapsed_readable": _format_duration(item["elapsed_hours"]),
            }
            for item in worst_offenders
        ],
        "next_steps": next_steps,
    }

    return WranglerScriptResult(
        script_id="highlight_stage_bottlenecks",
        status="success",
        message=message,
        payload=payload,
    )


__all__ = [
    "_build_render_volatility_report",
    "_run_escalate_deadline_shots_script",
    "_run_flag_frame_time_regressions_script",
    "_run_flag_render_error_streaks_script",
    "_run_flag_render_volatility_script",
    "_run_highlight_stage_bottlenecks_script",
    "_run_identify_unowned_shots_script",
    "_run_list_failing_jobs_script",
    "_run_rebuild_unstable_caches_script",
    "_run_spin_down_idle_workers_script",
]
