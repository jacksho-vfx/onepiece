from __future__ import annotations

import json
from datetime import datetime

import pytest

from apps.perona.engine import (
    CostModelInput,
    PeronaEngine,
    RenderMetric,
    ShotTelemetry,
)


class _StubMetricStore:
    def __init__(self, path):
        self._path = path

    @property
    def path(self):
        return self._path


@pytest.fixture()
def engine_with_stubbed_data(tmp_path, monkeypatch):
    baseline = CostModelInput(
        frame_count=100,
        average_frame_time_ms=100.0,
        gpu_hourly_rate=100.0,
        gpu_count=4,
        render_hours=0.0,
        render_farm_hourly_rate=80.0,
        storage_gb=0.0,
        storage_rate_per_gb=0.0,
        data_egress_gb=0.0,
        egress_rate_per_gb=0.0,
        misc_costs=0.0,
    )
    engine = PeronaEngine(baseline_input=baseline)

    telemetry = (
        ShotTelemetry(
            sequence="SQ01",
            shot_id="SH001",
            average_frame_time_ms=118.0,
            fps=24.0,
            error_rate=0.015,
            cache_stability=0.74,
            frames_rendered=400,
            deadline=datetime(2024, 5, 30, 12, 0),
        ),
    )
    engine._telemetry = telemetry

    render_log = (
        RenderMetric(
            sequence="SQ01",
            shot_id="SH001",
            timestamp=datetime(2024, 5, 20, 10, 0),
            fps=24.0,
            frame_time_ms=120.0,
            error_count=4,
            gpu_utilisation=0.72,
            cache_health=0.7,
        ),
    )
    engine._render_log = render_log
    engine._frame_times_by_shot = engine._group_frame_times(render_log)

    metrics_path = tmp_path / "metrics.ndjson"
    persisted_metric = {
        "sequence": "SQ01",
        "shot_id": "SH001",
        "timestamp": "2024-05-21T09:45:00",
        "fps": 24.0,
        "frame_time_ms": 150.0,
        "error_count": 2,
        "gpuUtilisation": 0.88,
        "cacheHealth": 0.9,
    }
    metrics_path.write_text(json.dumps(persisted_metric) + "\n", encoding="utf-8")

    from apps.perona.web import dashboard as dashboard_module

    monkeypatch.setattr(
        dashboard_module, "_metrics_store", _StubMetricStore(metrics_path)
    )

    return engine


def test_cost_training_dataset_includes_live_and_persisted_metrics(engine_with_stubbed_data):
    dataset = engine_with_stubbed_data._build_cost_training_dataset()

    assert len(dataset) == 2

    first, second = dataset

    assert first.feature_values["frame_time_ms"] == 120.0
    assert first.feature_values["gpu_utilisation"] == 0.72
    assert first.feature_values["error_count"] == 4.0
    assert first.feature_values["cache_health"] == 0.7
    assert first.feature_values["render_hours"] == pytest.approx(0.013333, rel=1e-3)
    assert first.cost == pytest.approx(2.4, rel=1e-3)

    assert second.feature_values["frame_time_ms"] == 150.0
    assert second.feature_values["gpu_utilisation"] == 0.88
    assert second.feature_values["error_count"] == 2.0
    assert second.feature_values["cache_health"] == 0.9
    assert second.feature_values["render_hours"] == pytest.approx(0.016667, rel=1e-3)
    assert second.cost == pytest.approx(3.0, rel=1e-3)


def test_cost_insights_returns_statistics_and_recommendations(engine_with_stubbed_data):
    stats, recommendations = engine_with_stubbed_data.cost_insights(top_n=2)

    frame_time_stats = next(stat for stat in stats if stat.name == "frame_time_ms")
    render_hours_stats = next(stat for stat in stats if stat.name == "render_hours")

    assert frame_time_stats.mean == pytest.approx(135.0)
    assert render_hours_stats.maximum == pytest.approx(0.016667, rel=1e-3)

    assert len(recommendations) == 2
    for message in recommendations:
        assert any(feature in message for feature in ("render_hours", "frame_time_ms", "gpu_utilisation", "error_count", "cache_health"))
