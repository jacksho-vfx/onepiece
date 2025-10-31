"""Wrangler scripts that analyse telemetry quality and utilisation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from apps.perona.web import dashboard as dashboard_module

from ..registry import WranglerScriptResult

_TARGET_GPU_UTILISATION = 0.8
_UTILISATION_TOLERANCE = 0.05
_MIN_CONCURRENCY_RATIO = 0.25
_MAX_CONCURRENCY_RATIO = 1.75

_TELEMETRY_HEALTHY_THRESHOLD_MINUTES = 30.0
_TELEMETRY_STALE_THRESHOLD_MINUTES = 120.0


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


def _parse_latest_timestamp(sample: Mapping[str, Any] | None) -> datetime | None:
    if not isinstance(sample, Mapping):
        return None

    raw_timestamp = sample.get("timestamp")
    if not isinstance(raw_timestamp, str):
        return None

    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(raw_timestamp)
    except ValueError:
        if raw_timestamp.endswith("Z"):
            try:
                parsed = datetime.fromisoformat(raw_timestamp[:-1] + "+00:00")
            except ValueError:
                parsed = None

    if parsed is None:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


def _classify_freshness(age_minutes: float) -> str:
    if age_minutes <= _TELEMETRY_HEALTHY_THRESHOLD_MINUTES:
        return "healthy"
    if age_minutes <= _TELEMETRY_STALE_THRESHOLD_MINUTES:
        return "warning"
    return "stale"


def _format_timestamp_iso(timestamp: datetime | None) -> str | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).isoformat()


def _run_check_telemetry_freshness_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    summary = dashboard_module.metrics_summary(engine=engine)

    total_samples = int(summary.get("total_samples", 0) or 0)
    latest_sample = summary.get("latest_sample")

    payload: dict[str, Any] = {
        "latest_sequence": None,
        "latest_shot": None,
        "latest_timestamp": None,
        "age_minutes": None,
        "status": None,
        "thresholds": {
            "healthy_minutes": _TELEMETRY_HEALTHY_THRESHOLD_MINUTES,
            "stale_minutes": _TELEMETRY_STALE_THRESHOLD_MINUTES,
        },
    }

    if total_samples <= 0 or not latest_sample:
        message = "No telemetry samples available; ingest render metrics before checking freshness."
        return WranglerScriptResult(
            script_id="check_telemetry_freshness",
            status="error",
            message=message,
            payload=payload,
        )

    timestamp = _parse_latest_timestamp(latest_sample)
    payload.update(
        {
            "latest_sequence": latest_sample.get("sequence"),
            "latest_shot": latest_sample.get("shot_id"),
            "latest_timestamp": latest_sample.get("timestamp"),
        }
    )

    if timestamp is None:
        message = "Latest telemetry sample is missing a valid timestamp; freshness is unknown."
        return WranglerScriptResult(
            script_id="check_telemetry_freshness",
            status="error",
            message=message,
            payload=payload,
        )

    now = datetime.utcnow()
    age_minutes = max(0.0, (now - timestamp).total_seconds() / 60.0)
    rounded_age = round(age_minutes, 1)
    status = _classify_freshness(age_minutes)

    payload.update({"age_minutes": rounded_age, "status": status})

    if status == "healthy":
        message = (
            f"Telemetry is fresh — latest sample arrived {rounded_age:.1f} minutes ago."
        )
    elif status == "warning":
        message = (
            f"Telemetry is ageing — latest sample is {rounded_age:.1f} minutes old."
        )
    else:
        message = (
            f"Telemetry is stale — latest sample is {rounded_age:.1f} minutes old."
        )

    return WranglerScriptResult(
        script_id="check_telemetry_freshness",
        status="success",
        message=message,
        payload=payload,
    )


def _build_telemetry_index(engine: Any) -> dict[tuple[str, str], Any]:
    telemetry_index: dict[tuple[str, str], Any] = {}
    telemetry = getattr(engine, "_telemetry", ())
    for sample in telemetry:
        key = (getattr(sample, "sequence", None), getattr(sample, "shot_id", None))
        if None not in key:
            telemetry_index[key] = sample  # type: ignore[index]
    return telemetry_index


def _run_audit_telemetry_coverage_script() -> WranglerScriptResult:
    engine = dashboard_module.get_engine()
    telemetry_index = _build_telemetry_index(engine)

    samples = list(engine.stream_render_metrics())
    metrics_by_shot: dict[tuple[str, str], list[Any]] = {}
    for sample in samples:
        key = (sample.sequence, sample.shot_id)
        metrics_by_shot.setdefault(key, []).append(sample)

    keys = set(telemetry_index) | set(metrics_by_shot)

    thresholds = {
        "healthy_minutes": _TELEMETRY_HEALTHY_THRESHOLD_MINUTES,
        "stale_minutes": _TELEMETRY_STALE_THRESHOLD_MINUTES,
    }

    counts = {"healthy": 0, "warning": 0, "stale": 0, "missing": 0}

    if not keys:
        message = (
            "Telemetry coverage audit unavailable — no telemetry samples recorded."
        )
        payload = {
            "summary": message,
            "shots": [],
            "counts": counts,
            "thresholds": thresholds,
            "attention_total": 0,
        }
        return WranglerScriptResult(
            script_id="audit_telemetry_coverage",
            status="success",
            message=message,
            payload=payload,
        )

    now_utc = datetime.now(timezone.utc)

    def _shot_entry(key: tuple[str, str]) -> dict[str, Any]:
        sequence, shot = key
        telemetry_present = key in telemetry_index
        metrics = metrics_by_shot.get(key, [])
        sample_count = len(metrics)
        last_seen: datetime | None = None
        age_minutes: float | None = None
        status: str

        if sample_count > 0:
            last_seen = max(  # type: ignore[type-var]
                (getattr(sample, "timestamp", None) for sample in metrics), default=None
            )
            if isinstance(last_seen, datetime):
                if last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                else:
                    last_seen = last_seen.astimezone(timezone.utc)
                age_minutes = max(0.0, (now_utc - last_seen).total_seconds() / 60.0)
                status = _classify_freshness(age_minutes)
            else:
                last_seen = None
                status = "missing"
        else:
            status = "missing"

        counts[status] = counts.get(status, 0) + 1

        entry = {
            "sequence": sequence,
            "shot": shot,
            "samples": sample_count,
            "last_seen": _format_timestamp_iso(last_seen),
            "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
            "status": status,
            "telemetry_present": telemetry_present,
        }
        return entry

    entries = [_shot_entry(key) for key in keys]

    severity = {"missing": 0, "stale": 1, "warning": 2, "healthy": 3}
    entries.sort(
        key=lambda item: (
            severity.get(item["status"], 4),
            -(item["age_minutes"] if item["age_minutes"] is not None else float("inf")),
            item["sequence"],
            item["shot"],
        )
    )

    attention_total = counts["warning"] + counts["stale"] + counts["missing"]
    if attention_total:
        breakdown: list[str] = []
        for bucket in ("missing", "stale", "warning"):
            if counts[bucket]:
                label = "warning" if bucket == "warning" else bucket
                breakdown.append(f"{counts[bucket]} {label}")
        detail = ", ".join(breakdown)
        message = f"{attention_total} shot(s) need telemetry attention"
        if detail:
            message += f" — {detail}."
        else:
            message += "."
    else:
        message = "All monitored shots have fresh telemetry coverage."

    payload = {
        "summary": message,
        "shots": entries,
        "counts": counts,
        "thresholds": thresholds,
        "attention_total": attention_total,
    }

    return WranglerScriptResult(
        script_id="audit_telemetry_coverage",
        status="success",
        message=message,
        payload=payload,
    )


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


__all__ = [
    "_TARGET_GPU_UTILISATION",
    "_UTILISATION_TOLERANCE",
    "_MIN_CONCURRENCY_RATIO",
    "_clamp",
    "_build_telemetry_index",
    "_format_timestamp_iso",
    "_run_audit_telemetry_coverage_script",
    "_run_boost_gpu_utilisation_script",
    "_run_check_telemetry_freshness_script",
]
