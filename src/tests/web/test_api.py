"""Integration smoke-tests for the Perona FastAPI surface."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from libraries.analytics.perona.engine import (
    CostBreakdown,
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_CURRENCY,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_SETTINGS_PATH,
    DEFAULT_TARGET_ERROR_RATE,
    OptimizationResult,
)
from libraries.analytics.perona.models import RenderMetric
from libraries.analytics.perona.ml_foundations import FeatureStatistics
from apps.perona.version import PERONA_VERSION
from apps.perona.web import dashboard as dashboard_module
from apps.perona.web import wrangler as wrangler_module
from apps.perona.web.dashboard import app, invalidate_engine_cache


client = TestClient(app)
KNOWN_SEQUENCES = {"SQ12", "SQ18", "SQ05", "SQ09"}


@pytest.fixture(autouse=True)
def _reset_wrangler_registry() -> Any:
    wrangler_module._reset_registry()
    yield
    wrangler_module._reset_registry()


def test_dashboard_ui_root_serves_html() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"].lower()
    assert "<title>Perona Dashboard</title>" in response.text


def test_wrangler_scripts_listing_returns_metadata() -> None:
    wrangler_module.register_script(
        wrangler_module.WranglerScriptMetadata(
            script_id="cache.refresh",
            name="Refresh cache",
            description="Rebuild cached analytics",
        ),
        lambda: {"status": "success", "message": "ok"},
    )

    response = client.get("/wrangler/scripts")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    scripts = {item["script_id"]: item for item in payload}
    assert scripts["analyse_cost_drivers"]["name"] == "Analyse cost drivers"
    assert "cost inputs" in scripts["analyse_cost_drivers"]["description"].lower()
    assert scripts["analyse_cost_drivers"]["tags"] == [
        "cost",
        "insights",
        "telemetry",
    ]
    assert "boost_gpu_utilisation" in scripts
    assert scripts["boost_gpu_utilisation"]["name"] == "Boost GPU utilisation"
    assert scripts["boost_gpu_utilisation"]["description"]
    assert scripts["boost_gpu_utilisation"]["tags"] == ["rendering", "utilisation"]

    assert scripts["spin_down_idle_workers"]["name"] == "Spin down idle GPU workers"
    assert "GPU nodes" in scripts["spin_down_idle_workers"]["description"]
    assert scripts["spin_down_idle_workers"]["tags"] == [
        "rendering",
        "capacity",
        "cost",
    ]

    assert scripts["list_failing_jobs"]["name"] == "List failing jobs"
    assert "critical shots" in scripts["list_failing_jobs"]["description"]
    assert scripts["list_failing_jobs"]["tags"] == ["risk", "shots"]

    assert scripts["rebuild_unstable_caches"]["name"] == "Rebuild unstable caches"
    assert (
        "cache stability" in scripts["rebuild_unstable_caches"]["description"].lower()
    )
    assert scripts["rebuild_unstable_caches"]["tags"] == [
        "risk",
        "caches",
        "simulation",
    ]

    assert scripts["explain_pnl_delta"]["name"] == "Explain P&L delta"
    assert "render spend" in scripts["explain_pnl_delta"]["description"].lower()
    assert scripts["explain_pnl_delta"]["tags"] == [
        "finance",
        "pnl",
        "insights",
    ]

    assert (
        scripts["escalate_deadline_shots"]["name"]
        == "Escalate deadline-sensitive shots"
    )
    assert "deadline" in scripts["escalate_deadline_shots"]["description"].lower()
    assert scripts["escalate_deadline_shots"]["tags"] == [
        "risk",
        "shots",
        "deadline",
    ]

    assert (
        scripts["highlight_stage_bottlenecks"]["name"]
        == "Highlight stage bottlenecks"
    )
    assert "busiest stage" in scripts["highlight_stage_bottlenecks"]["description"].lower()
    assert scripts["highlight_stage_bottlenecks"]["tags"] == [
        "production",
        "shots",
    ]

    assert scripts["cache.refresh"] == {
        "script_id": "cache.refresh",
        "name": "Refresh cache",
        "description": "Rebuild cached analytics",
        "tags": [],
    }


def test_wrangler_execute_missing_script_returns_404() -> None:
    response = client.post("/wrangler/scripts/unknown-task")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown Wrangler script."}


def test_wrangler_execute_script_returns_payload() -> None:
    async def runner() -> wrangler_module.WranglerScriptResult:
        return wrangler_module.WranglerScriptResult(
            script_id="reindex",
            status="success",
            message="Completed",
            payload={"refreshed": 12},
        )

    wrangler_module.register_script(
        wrangler_module.WranglerScriptMetadata(
            script_id="reindex",
            name="Reindex sequences",
            description="Refreshes downstream search indices",
        ),
        runner,
    )

    response = client.post("/wrangler/scripts/reindex")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "reindex"
    assert payload["status"] == "success"
    assert payload["message"] == "Completed"
    assert payload["payload"] == {"refreshed": 12}


def test_wrangler_boost_gpu_utilisation_script_reports_recommendations() -> None:
    response = client.post("/wrangler/scripts/boost_gpu_utilisation")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "boost_gpu_utilisation"
    assert payload["status"] == "success"
    assert payload["message"]
    assert "GPU utilisation" in payload["message"]

    body = payload["payload"]
    assert body["summary"] == payload["message"]
    overall = body["overall"]
    assert overall["average_utilisation"] >= 0
    assert overall["target_utilisation"] == pytest.approx(0.8)
    assert overall["status"] in {"below", "on", "above"}

    sequences = body["sequences"]
    assert sequences
    for item in sequences:
        assert item["sequence"]
        assert isinstance(item["recommendation"], str)
        assert item["recommendation"]


def test_wrangler_analyse_cost_drivers_script_returns_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statistics = (
        FeatureStatistics(
            name="frame_time_ms",
            mean=150.0,
            stddev=15.0,
            minimum=120.0,
            maximum=180.0,
        ),
        FeatureStatistics(
            name="gpu_hours",
            mean=12.5,
            stddev=1.2,
            minimum=8.0,
            maximum=16.0,
        ),
        FeatureStatistics(
            name="queue_depth",
            mean=5.0,
            stddev=0.5,
            minimum=4.0,
            maximum=6.5,
        ),
    )
    recommendations = (
        "Prioritise frame timing optimisations to stabilise renders.",
        "Tune GPU allocation for long-running shots.",
    )

    mock_engine = Mock()
    mock_engine.cost_insights.return_value = (statistics, recommendations)

    monkeypatch.setattr(dashboard_module, "get_engine", lambda: mock_engine)

    response = client.post("/wrangler/scripts/analyse_cost_drivers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "analyse_cost_drivers"
    assert payload["status"] == "success"
    assert "frame_time_ms" in payload["message"]

    body = payload["payload"]
    assert body["headline"] == payload["message"]
    top_features = body["top_features"]
    assert [item["feature"] for item in top_features] == [
        "frame_time_ms",
        "gpu_hours",
        "queue_depth",
    ]
    assert top_features[0]["delta"] == pytest.approx(60.0, rel=1e-4)
    assert top_features[1]["delta"] == pytest.approx(8.0, rel=1e-4)
    assert body["recommended_actions"] == list(recommendations)
    mock_engine.cost_insights.assert_called_once_with(top_n=5)


def test_wrangler_analyse_cost_drivers_script_handles_missing_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recommendations = ("Capture additional telemetry to build cost insights.",)

    mock_engine = Mock()
    mock_engine.cost_insights.return_value = ((), recommendations)

    monkeypatch.setattr(dashboard_module, "get_engine", lambda: mock_engine)

    response = client.post("/wrangler/scripts/analyse_cost_drivers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "analyse_cost_drivers"
    assert payload["status"] == "error"
    assert "unavailable" in payload["message"].lower()
    body = payload["payload"]
    assert body["top_features"] == []
    assert body["recommended_actions"] == list(recommendations)
    mock_engine.cost_insights.assert_called_once_with(top_n=5)


def test_wrangler_spin_down_script_recommends_smaller_worker_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DummyBaseline:
        def __init__(self, gpu_count: int) -> None:
            self.gpu_count = gpu_count

    class _DummyEngine:
        def __init__(self) -> None:
            self.baseline_cost_input = _DummyBaseline(24)

        def run_optimization_backtest(
            self, scenarios: list[Any]
        ) -> tuple[CostBreakdown, tuple[OptimizationResult, ...]]:
            assert scenarios[0].gpu_count == 10
            baseline = CostBreakdown(
                frame_count=1000,
                gpu_hours=240.0,
                render_hours=240.0,
                concurrency=self.baseline_cost_input.gpu_count,
                gpu_cost=960.0,
                render_farm_cost=320.0,
                storage_cost=50.0,
                egress_cost=25.0,
                misc_cost=10.0,
                total_cost=1365.0,
                cost_per_frame=1.365,
                currency="GBP",
            )
            result = OptimizationResult(
                name="Scale to 10 GPUs",
                total_cost=965.0,
                cost_per_frame=0.965,
                gpu_hours=160.0,
                render_hours=240.0,
                savings_vs_baseline=400.0,
                savings_percent=29.3,
                notes="Stub backtest",
            )
            return baseline, (result,)

    summary = {
        "total_samples": 42,
        "averages": {"gpu_utilisation": 0.35},
        "sequences": [],
        "latest_sample": None,
    }

    dummy_engine = _DummyEngine()
    monkeypatch.setattr(dashboard_module, "get_engine", lambda: dummy_engine)
    monkeypatch.setattr(
        dashboard_module,
        "metrics_summary",
        lambda engine: summary,
    )

    response = client.post("/wrangler/scripts/spin_down_idle_workers")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "spin_down_idle_workers"
    assert payload["status"] == "success"
    assert "below" in payload["message"]

    body = payload["payload"]
    assert body["baseline_worker_count"] == 24
    assert body["recommended_worker_count"] < body["baseline_worker_count"]
    assert body["projected_savings"]["amount"] == pytest.approx(400.0)
    assert any("Projected utilisation" in note for note in body["notes"])


def test_wrangler_escalate_deadline_shots_script_flags_deadline_risk() -> None:
    response = client.post("/wrangler/scripts/escalate_deadline_shots")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "escalate_deadline_shots"
    assert payload["status"] == "success"

    body = payload["payload"]
    assert body["total"] >= 1
    assert body["escalations"]

    first = body["escalations"][0]
    assert first["drivers"]
    assert any("deadline" in driver.lower() for driver in first["drivers"])
    assert "deadline_horizon" in first


def test_wrangler_explain_pnl_delta_script_returns_summary() -> None:
    response = client.post("/wrangler/scripts/explain_pnl_delta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "explain_pnl_delta"
    assert payload["status"] == "success"
    assert "delta" in payload["message"].lower()

    body = payload["payload"]
    totals = body["totals"]
    assert set(totals) == {"baseline", "current", "delta", "currency"}
    assert totals["currency"]
    assert totals["baseline"] == pytest.approx(
        body["per_frame"]["baseline"] * body["frame_count"], rel=1e-3
    )

    per_frame = body["per_frame"]
    assert set(per_frame) == {"baseline", "current", "delta"}

    contributions = body["contributions"]
    assert isinstance(contributions, list)
    assert contributions
    assert len(contributions) <= 3
    assert contributions[0]["rank"] == 1
    assert contributions[0]["factor"]
    assert contributions[0]["narrative"]
    assert isinstance(contributions[0]["delta_cost"], float)
    assert isinstance(contributions[0]["percentage_points"], float)
    assert contributions[0]["factor"] in payload["message"]


def test_wrangler_explain_pnl_delta_handles_missing_contributions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_breakdown = CostBreakdown(
        frame_count=DEFAULT_BASELINE_COST_INPUT.frame_count,
        gpu_hours=DEFAULT_BASELINE_COST_INPUT.render_hours
        * DEFAULT_BASELINE_COST_INPUT.gpu_count,
        render_hours=DEFAULT_BASELINE_COST_INPUT.render_hours,
        concurrency=DEFAULT_BASELINE_COST_INPUT.gpu_count,
        gpu_cost=DEFAULT_PNL_BASELINE_COST * 0.5,
        render_farm_cost=DEFAULT_PNL_BASELINE_COST * 0.25,
        storage_cost=DEFAULT_PNL_BASELINE_COST * 0.1,
        egress_cost=DEFAULT_PNL_BASELINE_COST * 0.05,
        misc_cost=DEFAULT_PNL_BASELINE_COST * 0.1,
        total_cost=DEFAULT_PNL_BASELINE_COST,
        cost_per_frame=DEFAULT_PNL_BASELINE_COST
        / DEFAULT_BASELINE_COST_INPUT.frame_count,
        currency=DEFAULT_CURRENCY,
    )

    pnl_breakdown = Mock()
    pnl_breakdown.baseline_cost = baseline_breakdown.total_cost
    pnl_breakdown.current_cost = baseline_breakdown.total_cost + 125.0
    pnl_breakdown.delta_cost = 125.0
    pnl_breakdown.contributions = ()

    mock_engine = Mock()
    mock_engine.baseline_cost_input = DEFAULT_BASELINE_COST_INPUT
    mock_engine.pnl_explainer.return_value = pnl_breakdown
    mock_engine.estimate_cost.return_value = baseline_breakdown

    monkeypatch.setattr(dashboard_module, "get_engine", lambda: mock_engine)

    response = client.post("/wrangler/scripts/explain_pnl_delta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "explain_pnl_delta"
    assert payload["status"] == "success"
    assert "no contribution" in payload["message"].lower()

    body = payload["payload"]
    assert body["contributions"] == []
    assert body["totals"]["delta"] == pytest.approx(125.0)
    assert body["per_frame"]["delta"] == pytest.approx(
        125.0 / DEFAULT_BASELINE_COST_INPUT.frame_count, rel=1e-3
    )

    mock_engine.pnl_explainer.assert_called_once_with()
    mock_engine.estimate_cost.assert_called_once_with(DEFAULT_BASELINE_COST_INPUT)


def test_wrangler_rebuild_unstable_caches_script_highlights_cache_risk() -> None:
    response = client.post("/wrangler/scripts/rebuild_unstable_caches")

    assert response.status_code == 200

    payload = response.json()
    assert payload["script_id"] == "rebuild_unstable_caches"
    assert payload["status"] == "success"
    assert "cache" in payload["message"].lower()

    body = payload["payload"]
    assert body["summary"] == payload["message"]
    assert body["total"] >= 1

    shots = body["shots"]
    assert shots

    first = shots[0]
    assert first["cache_stability"] < 0.75
    assert first["recommendation"]
    assert "rebuild" in first["recommendation"].lower()

    metrics = first["cache_metrics"]
    assert isinstance(metrics, dict)
    assert "resim_count" in metrics or "avg_cache_gb" in metrics
    if "resim_count" in metrics:
        assert metrics["resim_count"] >= 0
    if "avg_cache_gb" in metrics:
        assert metrics["avg_cache_gb"] > 0


def test_wrangler_list_failing_jobs_script_surfaces_critical_shots() -> None:
    response = client.post("/wrangler/scripts/list_failing_jobs")

    assert response.status_code == 200

    payload = response.json()
    assert payload["script_id"] == "list_failing_jobs"
    assert payload["status"] == "success"
    assert payload["message"]

    body = payload["payload"]
    assert body["headline"] == payload["message"]

    details = body["details"]
    assert details, "Expected at least one critical shot to be listed"
    risk_scores = [item["risk_score"] for item in details]
    assert risk_scores == sorted(risk_scores, reverse=True)

    for entry in details:
        assert {
            "sequence",
            "shot",
            "risk_score",
            "drivers",
            "recommended_follow_up",
        }.issubset(entry)
        assert isinstance(entry["drivers"], list)
        assert entry["drivers"]
        assert isinstance(entry["recommended_follow_up"], str)
        assert entry["recommended_follow_up"]


def test_wrangler_highlight_stage_bottlenecks_script_reports_active_load() -> None:
    response = client.post("/wrangler/scripts/highlight_stage_bottlenecks")

    assert response.status_code == 200

    payload = response.json()
    assert payload["script_id"] == "highlight_stage_bottlenecks"
    assert payload["status"] == "success"
    assert payload["message"]

    body = payload["payload"]
    assert body["summary"] == payload["message"]

    stage_counts = body["per_stage_counts"]
    assert isinstance(stage_counts, list)
    assert stage_counts, "Expected at least one stage count entry"
    assert any(entry["shots"] > 0 for entry in stage_counts)

    offenders = body["worst_offenders"]
    assert isinstance(offenders, list)
    assert offenders, "Expected at least one active shot entry"
    first = offenders[0]
    assert {
        "sequence",
        "shot",
        "current_stage",
    }.issubset(first)

    assert isinstance(body["next_steps"], list)
    assert body["next_steps"], "Expected suggested next steps"


def test_dashboard_summary_endpoint() -> None:
    response = client.get("/dashboard/summary")

    assert response.status_code == 200
    payload = response.json()

    assert {"generated_at", "metrics", "shots", "risk", "costs"}.issubset(payload)
    metrics = payload["metrics"]
    assert metrics["total_samples"] >= 0
    assert "average_fps" in metrics
    shots = payload["shots"]
    assert shots["total"] >= 0
    assert "by_stage" in shots


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_endpoint_defaults() -> None:
    response = client.get("/settings")
    assert response.status_code == 200
    data = response.json()

    assert data["target_error_rate"] == pytest.approx(DEFAULT_TARGET_ERROR_RATE)
    assert data["pnl_baseline_cost"] == pytest.approx(DEFAULT_PNL_BASELINE_COST)
    assert data["settings_path"] == str(DEFAULT_SETTINGS_PATH.expanduser())
    assert data["warnings"] == []

    baseline = data["baseline_cost_input"]
    assert baseline["frame_count"] == DEFAULT_BASELINE_COST_INPUT.frame_count
    assert baseline["gpu_hourly_rate"] == pytest.approx(
        DEFAULT_BASELINE_COST_INPUT.gpu_hourly_rate
    )
    assert baseline["currency"] == DEFAULT_CURRENCY


def test_app_version_matches_perona_version() -> None:
    assert app.version == PERONA_VERSION


def test_render_feed_limit() -> None:
    response = client.get("/render-feed", params={"limit": 5})
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5
    first = data[0]
    assert {"sequence", "shot_id", "fps"}.issubset(first.keys())


def test_render_feed_filters() -> None:
    params = {"sequence": "SQ18", "shot_id": "SQ18_SH220"}
    response = client.get("/render-feed", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data, "Expected filtered render feed to return samples"
    assert {item["sequence"] for item in data} == {"SQ18"}
    assert {item["shot_id"] for item in data} == {"SQ18_SH220"}


def test_cost_estimate_endpoint() -> None:
    payload = {
        "frame_count": 60,
        "average_frame_time_ms": 160,
        "gpu_hourly_rate": 8.5,
        "gpu_count": 16,
        "render_farm_hourly_rate": 4.5,
        "storage_gb": 4.2,
        "storage_rate_per_gb": 0.35,
        "misc_costs": 42.0,
    }
    response = client.post("/cost/estimate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["frame_count"] == 60
    assert data["total_cost"] == pytest.approx(43.49, rel=1e-4)
    assert data["cost_per_frame"] == pytest.approx(0.7249, rel=1e-4)
    assert data["currency"] == DEFAULT_CURRENCY


def test_cost_estimate_endpoint_supports_currency_override() -> None:
    payload = {
        "frame_count": 60,
        "average_frame_time_ms": 160,
        "gpu_hourly_rate": 8.5,
        "gpu_count": 16,
        "render_farm_hourly_rate": 4.5,
        "storage_gb": 4.2,
        "storage_rate_per_gb": 0.35,
        "misc_costs": 42.0,
        "currency": "USD",
    }
    response = client.post("/cost/estimate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "USD"


def test_cost_insights_endpoint_returns_payload() -> None:
    invalidate_engine_cache()
    response = client.get("/api/cost/insights", params={"top_n": 2})

    assert response.status_code == 200
    data = response.json()
    statistics = data["statistics"]
    assert isinstance(statistics, list)
    assert statistics, "Expected telemetry statistics to be returned"
    first_stat = statistics[0]
    assert {
        "name",
        "mean",
        "stddev",
        "minimum",
        "maximum",
    }.issubset(first_stat.keys())

    recommendations = data["recommendations"]
    assert isinstance(recommendations, list)
    assert len(recommendations) == 2
    assert data["settings_path"] == str(DEFAULT_SETTINGS_PATH.expanduser())


def test_cost_insights_endpoint_handles_missing_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalidate_engine_cache()

    mock_engine = Mock()
    mock_engine.cost_insights.return_value = ((), ())

    signature = ("ENV", "path", 123)
    memo = dashboard_module._CostInsightsMemo()
    entry = dashboard_module._EngineCacheEntry(
        engine=mock_engine,
        signature=signature,
        settings_path=None,
        warnings=(),
        insights=memo,
    )

    monkeypatch.setattr(dashboard_module, "_engine_cache", entry, raising=False)
    monkeypatch.setattr(dashboard_module, "_settings_signature", lambda: signature)
    monkeypatch.setattr(dashboard_module, "_load_engine", lambda refresh: mock_engine)

    response = client.get("/api/cost/insights")

    assert response.status_code == 404
    assert response.json() == {"detail": "No telemetry statistics available."}


def test_settings_signature_uses_high_resolution_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sub-second settings changes should invalidate the cache signature."""

    class _FakeStat:
        def __init__(self, mtime_ns: int) -> None:
            self.st_mtime = 1000.0
            self.st_mtime_ns = mtime_ns

    class _FakePath:
        def __init__(self) -> None:
            self._calls = 0

        def expanduser(self) -> "_FakePath":
            return self

        def exists(self) -> bool:
            return True

        def stat(self) -> _FakeStat:
            self._calls += 1
            # st_mtime remains the same while the nanosecond value changes.
            return _FakeStat(1_500_000_000_000 + self._calls)

        def __str__(self) -> str:  # pragma: no cover - convenience for debugging
            return "/fake/settings.toml"

    fake_path = _FakePath()

    monkeypatch.setenv("PERONA_SETTINGS_PATH", "/fake/settings.toml")
    monkeypatch.setattr(dashboard_module, "_resolved_settings_path", lambda: fake_path)

    first_signature = dashboard_module._settings_signature()
    second_signature = dashboard_module._settings_signature()

    assert first_signature != second_signature


def test_risk_heatmap_endpoint() -> None:
    response = client.get("/risk-heatmap")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 3
    assert data[0]["risk_score"] >= data[-1]["risk_score"]


def test_pnl_endpoint() -> None:
    response = client.get("/pnl")
    assert response.status_code == 200
    data = response.json()
    contributions = sum(item["delta_cost"] for item in data["contributions"])
    assert data["delta_cost"] == pytest.approx(contributions)
    assert data["current_cost"] == pytest.approx(
        data["baseline_cost"] + data["delta_cost"]
    )


def test_optimization_backtest_endpoint() -> None:
    payload = {
        "scenarios": [
            {
                "name": "Dual Hopper",
                "gpu_count": 80,
                "gpu_hourly_rate": 7.4,
                "frame_time_scale": 0.85,
                "sampling_scale": 0.95,
            }
        ]
    }
    response = client.post("/optimization/backtest", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "baseline" in data
    assert len(data["scenarios"]) == 1
    scenario = data["scenarios"][0]
    assert scenario["total_cost"] < data["baseline"]["total_cost"]
    assert scenario["savings_vs_baseline"] > 0
    assert scenario["savings_percent"] > 0


def test_shots_lifecycle_endpoint() -> None:
    response = client.get("/shots/lifecycle")
    assert response.status_code == 200
    data = response.json()
    assert data
    assert {"sequence", "shot_id", "current_stage"}.issubset(data[0].keys())


def test_shots_sequences_endpoint() -> None:
    response = client.get("/shots/sequences")
    assert response.status_code == 200
    data = response.json()
    assert data

    names = [item["name"] for item in data]
    assert len(names) == len(set(names))

    for sequence in data:
        shot_ids = [shot["shot_id"] for shot in sequence["shots"]]
        assert shot_ids == sorted(shot_ids)


def test_shots_summary_filters_by_sequence() -> None:
    response = client.get("/shots", params={"sequence": "SQ05"})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["completed"] == 1
    assert data["active"] == 0
    assert data["by_sequence"] == [{"name": "SQ05", "shots": 1}]
    assert not data["active_shots"]


def test_shots_lifecycle_filters_by_artist() -> None:
    response = client.get("/shots/lifecycle", params={"artist": "M. Chen"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    shot = data[0]
    assert shot["sequence"] == "SQ12"
    assert shot["shot_id"] == "SQ12_SH010"


def test_shots_filters_by_date_range() -> None:
    params = {
        "start_date": "2024-05-17T12:00:00",
        "end_date": "2024-05-18T00:00:00",
    }
    response = client.get("/shots", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 4
    sequences = {item["name"] for item in data["by_sequence"]}
    assert "SQ05" in sequences
    assert "SQ05" not in {shot["sequence"] for shot in data["active_shots"]}


def test_shots_filters_include_active_stages_within_window() -> None:
    now = datetime.utcnow()
    params = {
        "start_date": (now - timedelta(hours=1)).isoformat(timespec="seconds"),
        "end_date": (now + timedelta(hours=1)).isoformat(timespec="seconds"),
    }
    response = client.get("/shots", params=params)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert {item["name"] for item in data["by_sequence"]} == {
        "SQ12",
        "SQ18",
        "SQ09",
    }
    active_sequences = {shot["sequence"] for shot in data["active_shots"]}
    assert {"SQ12", "SQ18", "SQ09"}.issubset(active_sequences)


def test_shot_sequences_support_filters() -> None:
    response = client.get("/shots/sequences", params={"artist": "R. Ali"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    sequence = data[0]
    assert sequence["name"] == "SQ18"
    assert {shot["shot_id"] for shot in sequence["shots"]} == {"SQ18_SH220"}


def test_render_feed_stream() -> None:
    with client.stream("GET", "/render-feed/live", params={"limit": 3}) as response:
        assert response.status_code == 200
        payloads: list[dict[str, object]] = []
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            payloads.append(json.loads(raw_line))
    assert len(payloads) == 3
    assert all("gpuUtilisation" in item for item in payloads)


def test_render_feed_stream_filters() -> None:
    params = {"sequence": "SQ05", "shot_id": "SQ05_SH045", "limit": 2}
    with client.stream("GET", "/render-feed/live", params=params) as response:  # type: ignore[arg-type]
        assert response.status_code == 200
        payloads: list[dict[str, object]] = []
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            payloads.append(json.loads(raw_line))
    assert len(payloads) == 2
    assert {item["sequence"] for item in payloads} == {"SQ05"}
    assert {item["shot_id"] for item in payloads} == {"SQ05_SH045"}


def test_metrics_summary_endpoint() -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    data = response.json()
    assert data["total_samples"] > 0
    assert data["averages"]["fps"] > 0
    assert data["latest_sample"]["sequence"] in KNOWN_SEQUENCES
    assert any(entry["sequence"] in KNOWN_SEQUENCES for entry in data["sequences"])


def test_metrics_summary_matches_manual_calculation() -> None:
    engine = dashboard_module.get_engine()
    samples = list(engine.stream_render_metrics())

    summary = dashboard_module.metrics_summary(engine=engine)

    assert summary["total_samples"] == len(samples)

    def _rounded_mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

    expected_averages = {
        "fps": _rounded_mean([sample.fps for sample in samples]),
        "frame_time_ms": _rounded_mean([sample.frame_time_ms for sample in samples]),
        "gpu_utilisation": _rounded_mean(
            [sample.gpu_utilisation for sample in samples]
        ),
        "error_count": _rounded_mean([sample.error_count for sample in samples]),
    }

    assert summary["averages"] == expected_averages

    expected_sequence_stats: dict[str, dict[str, Any]] = {}
    for sample in samples:
        entry = expected_sequence_stats.setdefault(
            sample.sequence,
            {
                "shots": set(),
                "fps": [],
                "frame_time_ms": [],
                "gpu_utilisation": [],
                "error_count": [],
            },
        )
        entry["shots"].add(sample.shot_id)
        entry["fps"].append(sample.fps)
        entry["frame_time_ms"].append(sample.frame_time_ms)
        entry["gpu_utilisation"].append(sample.gpu_utilisation)
        entry["error_count"].append(sample.error_count)

    summary_sequences = {item["sequence"]: item for item in summary["sequences"]}

    assert set(summary_sequences) == set(expected_sequence_stats)

    for name, data in expected_sequence_stats.items():
        expected_entry = {
            "sequence": name,
            "shots": len(data["shots"]),
            "avg_fps": _rounded_mean(data["fps"]),
            "avg_frame_time_ms": _rounded_mean(data["frame_time_ms"]),
            "avg_gpu_utilisation": _rounded_mean(data["gpu_utilisation"]),
            "avg_error_count": _rounded_mean(data["error_count"]),
        }
        assert summary_sequences[name] == expected_entry

    latest_expected = max(samples, key=lambda sample: sample.timestamp)
    expected_payload = RenderMetric.from_entity(latest_expected).model_dump(
        mode="json", by_alias=True
    )

    assert summary["latest_sample"] == expected_payload


def test_shots_summary_endpoint() -> None:
    response = client.get("/shots")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 4
    sequences = {item["name"] for item in data["by_sequence"]}
    assert KNOWN_SEQUENCES.issubset(sequences)
    assert any(shot["current_stage"] for shot in data["active_shots"])


def test_risk_summary_endpoint() -> None:
    response = client.get("/risk")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] >= 3
    assert data["max_risk"] >= data["min_risk"]
    assert len(data["top_risks"]) <= 3
    for critical in data["critical"]:
        assert critical["risk_score"] >= 75


def test_costs_summary_endpoint() -> None:
    response = client.get("/costs")
    assert response.status_code == 200
    data = response.json()
    assert data["baseline"]["currency"] == DEFAULT_CURRENCY
    assert {"baseline", "current", "delta"}.issubset(data["cost_per_frame"].keys())
    assert data["cost_per_frame"]["baseline"] == pytest.approx(
        data["baseline"]["cost_per_frame"], rel=1e-6
    )
    expected_current = data["pnl"]["current_cost"] / data["baseline"]["frame_count"]
    assert data["cost_per_frame"]["current"] == pytest.approx(
        expected_current, rel=1e-4
    )
    delta = data["cost_per_frame"]["current"] - data["cost_per_frame"]["baseline"]
    assert data["cost_per_frame"]["delta"] == pytest.approx(delta, rel=1e-4)


def test_daily_report_csv_export() -> None:
    response = client.get("/reports/daily", params={"format": "csv"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert (
        'attachment; filename="perona_daily_summary_'
        in response.headers["content-disposition"]
    )

    body = response.content.decode("utf-8")
    lines = body.splitlines()
    assert lines[0] == "metric,value"
    assert any(line.startswith("metrics.total_samples,") for line in lines)
    assert any("risk.top_risks[1].risk_score" in line for line in lines)


def test_daily_report_pdf_export() -> None:
    response = client.get("/reports/daily", params={"format": "pdf"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert len(response.content) > 200


def test_daily_report_rejects_unknown_format() -> None:
    response = client.get("/reports/daily", params={"format": "txt"})
    assert response.status_code == 400
    data = response.json()
    assert data["detail"] == "Unsupported format. Use 'csv' or 'pdf'."


def test_metrics_websocket_stream() -> None:
    with client.websocket_connect("/ws/metrics") as websocket:
        payload_one = websocket.receive_json()
        payload_two = websocket.receive_json()
    assert payload_one["sequence"] in KNOWN_SEQUENCES
    assert payload_two["shot_id"].startswith("SQ")


def test_settings_reload_between_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings updates apply without restarting the FastAPI app."""

    invalidate_engine_cache()

    override = tmp_path / "perona.toml"
    override.write_text(
        """
target_error_rate = 0.015
pnl_baseline_cost = 3210.0

[baseline_cost_input]
frame_count = 144
gpu_hourly_rate = 6.75
    """
    )

    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(override))

    initial_response = client.get("/settings")
    assert initial_response.status_code == 200
    initial_data = initial_response.json()
    assert initial_data["target_error_rate"] == pytest.approx(0.015)
    assert initial_data["pnl_baseline_cost"] == pytest.approx(3210.0)
    assert initial_data["baseline_cost_input"]["gpu_hourly_rate"] == pytest.approx(6.75)

    override.write_text(
        """
target_error_rate = 0.025
pnl_baseline_cost = 4567.0

[baseline_cost_input]
frame_count = 188
gpu_hourly_rate = 8.5
    """
    )
    os.utime(override, None)

    reload_response = client.post("/settings/reload")
    assert reload_response.status_code == 200
    reload_data = reload_response.json()
    assert reload_data["target_error_rate"] == pytest.approx(0.025)
    assert reload_data["pnl_baseline_cost"] == pytest.approx(4567.0)
    assert reload_data["baseline_cost_input"]["frame_count"] == 188

    pnl_response = client.get("/pnl")
    assert pnl_response.status_code == 200
    pnl_data = pnl_response.json()
    assert pnl_data["baseline_cost"] == pytest.approx(4567.0)

    final_settings = client.get("/settings")
    assert final_settings.status_code == 200
    final_data = final_settings.json()
    assert final_data["baseline_cost_input"]["gpu_hourly_rate"] == pytest.approx(8.5)

    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)
    invalidate_engine_cache()


def test_settings_endpoint_honours_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalidate_engine_cache()

    override = tmp_path / "custom.toml"
    override.write_text(
        """
target_error_rate = 0.042
pnl_baseline_cost = 9876.5

[baseline_cost_input]
frame_count = 128
average_frame_time_ms = 132.5
gpu_hourly_rate = 5.5
    """
    )

    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(override))

    first_response = client.get("/settings")
    assert first_response.status_code == 200
    first_data = first_response.json()
    assert first_data["settings_path"] == str(override)
    assert first_data["target_error_rate"] == pytest.approx(0.042)
    assert first_data["pnl_baseline_cost"] == pytest.approx(9876.5)
    assert first_data["baseline_cost_input"]["frame_count"] == 128

    override.write_text(
        """
target_error_rate = 0.12
pnl_baseline_cost = 5432.1

[baseline_cost_input]
frame_count = 96
gpu_hourly_rate = 4.25
    """
    )
    os.utime(override, None)

    second_response = client.get("/settings")
    assert second_response.status_code == 200
    second_data = second_response.json()
    assert second_data["settings_path"] == str(override)
    assert second_data["target_error_rate"] == pytest.approx(0.12)
    assert second_data["pnl_baseline_cost"] == pytest.approx(5432.1)
    assert second_data["baseline_cost_input"]["frame_count"] == 96
    assert second_data["baseline_cost_input"]["gpu_hourly_rate"] == pytest.approx(4.25)

    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)
    invalidate_engine_cache()

    default_response = client.get("/pnl")
    assert default_response.status_code == 200
    default_cost = default_response.json()["baseline_cost"]

    override_a = tmp_path / "override_a.toml"
    override_a.write_text("pnl_baseline_cost = 4321.0\n")

    override_b = tmp_path / "override_b.toml"
    override_b.write_text(
        """
pnl_baseline_cost = 2468.0

[baseline_cost_input]
frame_count = 12
average_frame_time_ms = 120.0
gpu_hourly_rate = 4.5
gpu_count = 8
render_farm_hourly_rate = 1.25
storage_gb = 1.5
storage_rate_per_gb = 0.2
data_egress_gb = 0.5
egress_rate_per_gb = 0.1
misc_costs = 12.5
"""
    )

    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(override_a))
    response_a = client.get("/pnl")
    assert response_a.status_code == 200
    assert response_a.json()["baseline_cost"] == pytest.approx(4321.0)

    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(override_b))
    response_b = client.get("/pnl")
    assert response_b.status_code == 200
    assert response_b.json()["baseline_cost"] == pytest.approx(2468.0)

    override_b.write_text(
        """
pnl_baseline_cost = 6543.0

[baseline_cost_input]
frame_count = 18
average_frame_time_ms = 160.0
gpu_hourly_rate = 7.0
"""
    )
    os.utime(override_b, None)

    refreshed = client.get("/pnl")
    assert refreshed.status_code == 200
    assert refreshed.json()["baseline_cost"] == pytest.approx(6543.0)

    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)
    restored = client.get("/pnl")
    assert restored.status_code == 200
    assert restored.json()["baseline_cost"] == pytest.approx(default_cost)

    invalidate_engine_cache()


def test_settings_endpoint_reports_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalidate_engine_cache()

    missing_path = tmp_path / "missing.toml"
    monkeypatch.setenv("PERONA_SETTINGS_PATH", str(missing_path))

    response = client.get("/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["settings_path"] == str(DEFAULT_SETTINGS_PATH.expanduser())
    assert data["warnings"]
    assert any("falling back to defaults" in warning for warning in data["warnings"])

    monkeypatch.delenv("PERONA_SETTINGS_PATH", raising=False)
    invalidate_engine_cache()


def test_metrics_ingest_persists_payload(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.ndjson"
    original_store = dashboard_module._metrics_store
    dashboard_module._metrics_store = dashboard_module.RenderMetricStore(metrics_path)
    try:
        payload = {
            "metrics": [
                {
                    "sequence": "SQ42",
                    "shot_id": "SQ42_SH010",
                    "timestamp": "2024-05-20T12:30:00Z",
                    "fps": 24.0,
                    "frame_time_ms": 125.6,
                    "error_count": 2,
                    "gpuUtilisation": 0.78,
                    "cacheHealth": 0.91,
                }
            ]
        }

        response = client.post("/api/metrics", json=payload)
        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "enqueued": 1}

        assert metrics_path.exists()
        contents = metrics_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(contents) == 1
        stored = json.loads(contents[0])
        assert stored["sequence"] == "SQ42"
        assert stored["shot_id"] == "SQ42_SH010"
        assert stored["timestamp"] == "2024-05-20T12:30:00Z"
        assert stored["gpuUtilisation"] == pytest.approx(0.78)
    finally:
        dashboard_module._metrics_store = original_store


def test_metrics_ingest_rejects_empty_payload(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.ndjson"
    original_store = dashboard_module._metrics_store
    dashboard_module._metrics_store = dashboard_module.RenderMetricStore(metrics_path)
    try:
        response = client.post("/api/metrics", json={"metrics": []})
        assert response.status_code == 400
        body = response.json()
        assert body["detail"] == "No metrics supplied."
        assert not metrics_path.exists()
    finally:
        dashboard_module._metrics_store = original_store
