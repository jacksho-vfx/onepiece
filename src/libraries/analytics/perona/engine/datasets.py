"""Dataset builders and telemetry helpers used by the Perona engine."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

from libraries.analytics.perona.ml_foundations import Dataset, TrainingExample

from .models import (
    CostBreakdown,
    CostModelInput,
    RenderMetric,
    ShotLifecycle,
    ShotLifecycleStage,
    ShotTelemetry,
)

LOGGER = logging.getLogger(__name__)


def build_default_telemetry() -> tuple[ShotTelemetry, ...]:
    return (
        ShotTelemetry(
            sequence="SQ12",
            shot_id="SQ12_SH010",
            average_frame_time_ms=168.0,
            fps=23.7,
            error_rate=0.028,
            cache_stability=0.71,
            frames_rendered=420,
            deadline=datetime(2024, 5, 21, 18, 0),
        ),
        ShotTelemetry(
            sequence="SQ18",
            shot_id="SQ18_SH220",
            average_frame_time_ms=152.0,
            fps=24.0,
            error_rate=0.014,
            cache_stability=0.82,
            frames_rendered=512,
            deadline=datetime(2024, 5, 24, 12, 0),
        ),
        ShotTelemetry(
            sequence="SQ05",
            shot_id="SQ05_SH045",
            average_frame_time_ms=139.0,
            fps=24.0,
            error_rate=0.009,
            cache_stability=0.9,
            frames_rendered=368,
            deadline=datetime(2024, 5, 28, 9, 0),
        ),
        ShotTelemetry(
            sequence="SQ09",
            shot_id="SQ09_SH180",
            average_frame_time_ms=181.0,
            fps=23.5,
            error_rate=0.032,
            cache_stability=0.64,
            frames_rendered=488,
            deadline=datetime(2024, 5, 21, 9, 0),
        ),
    )


def build_default_render_log(
    telemetry: Sequence[ShotTelemetry],
) -> tuple[RenderMetric, ...]:
    base_time = datetime(2024, 5, 20, 8, 30)
    samples: list[RenderMetric] = []
    for index, telemetry_item in enumerate(telemetry):
        for offset in range(3):
            timestamp = base_time + timedelta(minutes=7 * index + 4 * offset)
            samples.append(
                RenderMetric(
                    sequence=telemetry_item.sequence,
                    shot_id=telemetry_item.shot_id,
                    timestamp=timestamp,
                    fps=round(max(telemetry_item.fps - offset * 0.12, 18.0), 2),
                    frame_time_ms=round(
                        telemetry_item.average_frame_time_ms * (1 + 0.015 * offset), 2
                    ),
                    error_count=max(
                        0,
                        int(
                            telemetry_item.error_rate
                            * telemetry_item.frames_rendered
                            * 0.5
                        )
                        - offset,
                    ),
                    gpu_utilisation=round(
                        max(0.48, min(0.96, 0.62 + 0.05 * offset - index * 0.02)), 3
                    ),
                    cache_health=telemetry_item.cache_stability,
                )
            )
    samples.sort(key=lambda metric: metric.timestamp)
    return tuple(samples)


def build_default_lifecycle() -> tuple[ShotLifecycle, ...]:
    base_day = datetime(2024, 5, 18, 9, 0)
    lifecycles: list[ShotLifecycle] = []
    lifecycles.append(
        ShotLifecycle(
            sequence="SQ12",
            shot_id="SQ12_SH010",
            stages=(
                ShotLifecycleStage(
                    name="layout",
                    started_at=base_day - timedelta(days=12),
                    completed_at=base_day - timedelta(days=9, hours=3),
                    metrics={"owner": "D. Vega", "notes": "Hero creature blocking"},
                ),
                ShotLifecycleStage(
                    name="sim",
                    started_at=base_day - timedelta(days=9, hours=2),
                    completed_at=base_day - timedelta(days=4, hours=6),
                    metrics={"avg_cache_gb": 1.8, "resim_count": 4},
                ),
                ShotLifecycleStage(
                    name="lighting",
                    started_at=base_day - timedelta(days=4, hours=4),
                    completed_at=None,
                    metrics={"avg_render_time_ms": 168.0, "artist": "M. Chen"},
                ),
                ShotLifecycleStage(
                    name="comp",
                    started_at=base_day - timedelta(days=1),
                    completed_at=None,
                    metrics={"status": "Awaiting lighting caches"},
                ),
            ),
        )
    )
    lifecycles.append(
        ShotLifecycle(
            sequence="SQ18",
            shot_id="SQ18_SH220",
            stages=(
                ShotLifecycleStage(
                    name="layout",
                    started_at=base_day - timedelta(days=10),
                    completed_at=base_day - timedelta(days=7),
                    metrics={"owner": "P. Singh"},
                ),
                ShotLifecycleStage(
                    name="sim",
                    started_at=base_day - timedelta(days=7, hours=2),
                    completed_at=base_day - timedelta(days=3, hours=12),
                    metrics={"avg_cache_gb": 1.2, "resim_count": 2},
                ),
                ShotLifecycleStage(
                    name="lighting",
                    started_at=base_day - timedelta(days=3, hours=10),
                    completed_at=base_day - timedelta(days=1, hours=5),
                    metrics={"avg_render_time_ms": 152.0, "artist": "R. Ali"},
                ),
                ShotLifecycleStage(
                    name="comp",
                    started_at=base_day - timedelta(days=1, hours=4),
                    completed_at=None,
                    metrics={"status": "Review with supe"},
                ),
            ),
        )
    )
    lifecycles.append(
        ShotLifecycle(
            sequence="SQ05",
            shot_id="SQ05_SH045",
            stages=(
                ShotLifecycleStage(
                    name="layout",
                    started_at=base_day - timedelta(days=8),
                    completed_at=base_day - timedelta(days=6, hours=5),
                    metrics={"owner": "Y. Ito"},
                ),
                ShotLifecycleStage(
                    name="sim",
                    started_at=base_day - timedelta(days=6, hours=3),
                    completed_at=base_day - timedelta(days=5),
                    metrics={"avg_cache_gb": 0.9, "resim_count": 1},
                ),
                ShotLifecycleStage(
                    name="lighting",
                    started_at=base_day - timedelta(days=5, hours=2),
                    completed_at=base_day - timedelta(days=2),
                    metrics={"avg_render_time_ms": 139.0, "artist": "K. Lopez"},
                ),
                ShotLifecycleStage(
                    name="comp",
                    started_at=base_day - timedelta(days=2, hours=1),
                    completed_at=base_day - timedelta(hours=18),
                    metrics={"status": "Final"},
                ),
            ),
        )
    )
    lifecycles.append(
        ShotLifecycle(
            sequence="SQ09",
            shot_id="SQ09_SH180",
            stages=(
                ShotLifecycleStage(
                    name="layout",
                    started_at=base_day - timedelta(days=14),
                    completed_at=base_day - timedelta(days=11, hours=6),
                    metrics={"owner": "N. Wolfe"},
                ),
                ShotLifecycleStage(
                    name="sim",
                    started_at=base_day - timedelta(days=11, hours=5),
                    completed_at=base_day - timedelta(days=6),
                    metrics={"avg_cache_gb": 2.4, "resim_count": 6},
                ),
                ShotLifecycleStage(
                    name="lighting",
                    started_at=base_day - timedelta(days=6, hours=2),
                    completed_at=None,
                    metrics={"avg_render_time_ms": 181.0, "artist": "C. Ramos"},
                ),
                ShotLifecycleStage(
                    name="comp",
                    started_at=base_day - timedelta(days=2, hours=12),
                    completed_at=None,
                    metrics={"status": "Temp slap"},
                ),
            ),
        )
    )
    return tuple(lifecycles)


def group_frame_times(
    render_log: Sequence[RenderMetric],
) -> dict[tuple[str, str], tuple[float, ...]]:
    """Build an index of frame times keyed by ``(sequence, shot_id)``."""

    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for sample in render_log:
        grouped[(sample.sequence, sample.shot_id)].append(sample.frame_time_ms)
    return {key: tuple(values) for key, values in grouped.items()}


def parse_metric_timestamp(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_persisted_render_metrics(
    render_log: Sequence[RenderMetric],
) -> tuple[RenderMetric, ...]:
    """Return metrics ingested via the API that are not in the boot log."""

    try:
        from apps.perona.web import dashboard as dashboard_module
    except Exception:  # pragma: no cover - defensive guard for optional import
        return ()

    metrics_store = getattr(dashboard_module, "_metrics_store", None)
    path = getattr(metrics_store, "path", None)
    if not isinstance(path, Path) or not path.exists():
        return ()

    existing = {
        (metric.sequence, metric.shot_id, metric.timestamp) for metric in render_log
    }
    fresh: list[RenderMetric] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp_raw = payload.get("timestamp")
                if not isinstance(timestamp_raw, str):
                    continue
                timestamp = parse_metric_timestamp(timestamp_raw)
                if timestamp is None:
                    continue

                sequence = payload.get("sequence")
                shot_id = payload.get("shot_id")
                frame_time = payload.get("frame_time_ms")
                gpu_utilisation = payload.get("gpuUtilisation")
                cache_health = payload.get("cacheHealth")

                if not (
                    isinstance(sequence, str)
                    and isinstance(shot_id, str)
                    and frame_time is not None
                    and gpu_utilisation is not None
                    and cache_health is not None
                ):
                    continue

                key = (sequence, shot_id, timestamp)
                if key in existing:
                    continue

                try:
                    metric = RenderMetric(
                        sequence=sequence,
                        shot_id=shot_id,
                        timestamp=timestamp,
                        fps=float(payload.get("fps", 0.0)),
                        frame_time_ms=float(frame_time),
                        error_count=int(payload.get("error_count", 0)),
                        gpu_utilisation=float(gpu_utilisation),
                        cache_health=float(cache_health),
                    )
                except (TypeError, ValueError):
                    continue

                existing.add(key)
                fresh.append(metric)
    except OSError:
        return ()

    fresh.sort(key=lambda metric: metric.timestamp)
    return tuple(fresh)


def build_cost_training_dataset(
    telemetry: Sequence[ShotTelemetry],
    render_log: Sequence[RenderMetric],
    baseline_cost_input: CostModelInput,
    estimate_cost: Callable[[CostModelInput], CostBreakdown],
    *,
    persisted_metrics: Sequence[RenderMetric] | None = None,
) -> Dataset:
    """Assemble a dataset that links render telemetry to realised costs."""

    telemetry_index = {(item.sequence, item.shot_id): item for item in telemetry}

    samples: list[RenderMetric] = list(render_log)
    if persisted_metrics is None:
        persisted_metrics = load_persisted_render_metrics(render_log)
    samples.extend(persisted_metrics)
    samples.sort(key=lambda m: m.timestamp.astimezone(timezone.utc))

    metrics_by_shot: dict[tuple[str, str], list[RenderMetric]] = defaultdict(list)
    for sample in samples:
        key = (sample.sequence, sample.shot_id)
        if key in telemetry_index:
            metrics_by_shot[key].append(sample)

    default_render_hours = baseline_cost_input.render_hours or (
        baseline_cost_input.frame_count
        * baseline_cost_input.average_frame_time_ms
        / 1000.0
        / 3600.0
    )

    examples: list[TrainingExample] = []
    for key, telemetry_item in telemetry_index.items():
        samples_for_shot = metrics_by_shot.get(key)
        if not samples_for_shot:
            estimated_errors = (
                telemetry_item.error_rate * telemetry_item.frames_rendered
            )
            samples_for_shot = [
                RenderMetric(
                    sequence=telemetry_item.sequence,
                    shot_id=telemetry_item.shot_id,
                    timestamp=telemetry_item.deadline,
                    fps=telemetry_item.fps,
                    frame_time_ms=telemetry_item.average_frame_time_ms,
                    error_count=int(round(estimated_errors)),
                    gpu_utilisation=0.75,
                    cache_health=telemetry_item.cache_stability,
                )
            ]

        for sample in samples_for_shot:
            render_hours = (
                telemetry_item.frames_rendered * sample.frame_time_ms / 1000.0 / 3600.0
            )
            if render_hours <= 0:
                render_hours = default_render_hours

            frame_count = (
                telemetry_item.frames_rendered or baseline_cost_input.frame_count
            )

            adjusted_input = replace(
                baseline_cost_input,
                average_frame_time_ms=sample.frame_time_ms,
                frame_count=frame_count,
                render_hours=render_hours,
            )
            breakdown = estimate_cost(adjusted_input)

            features = {
                "frame_time_ms": float(sample.frame_time_ms),
                "gpu_utilisation": float(sample.gpu_utilisation),
                "error_count": float(sample.error_count),
                "cache_health": float(sample.cache_health),
                "render_hours": float(render_hours),
            }

            examples.append(
                TrainingExample(feature_values=features, cost=breakdown.total_cost)
            )

    return Dataset(examples)


__all__ = [
    "build_cost_training_dataset",
    "build_default_lifecycle",
    "build_default_render_log",
    "build_default_telemetry",
    "group_frame_times",
    "load_persisted_render_metrics",
    "parse_metric_timestamp",
]
