from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from apps.perona.web import dashboard as dashboard_module
from apps.perona.web import wrangler as wrangler_module
from apps.perona.web.dashboard import app
from libraries.analytics.perona.engine import (
    CostBreakdown,
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_CURRENCY,
    DEFAULT_PNL_BASELINE_COST,
    OptimizationResult,
    RenderMetric as EngineRenderMetric,
    ShotLifecycle,
    ShotLifecycleStage,
    ShotTelemetry,
)
from libraries.analytics.perona.ml_foundations import FeatureStatistics

client = TestClient(app)


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

    assert scripts["audit_telemetry_coverage"]["name"] == "Audit telemetry coverage"
    assert "telemetry" in scripts["audit_telemetry_coverage"]["description"].lower()
    assert scripts["audit_telemetry_coverage"]["tags"] == [
        "telemetry",
        "coverage",
        "health",
    ]

    assert scripts["check_telemetry_freshness"]["name"] == "Check telemetry freshness"
    assert "telemetry" in scripts["check_telemetry_freshness"]["description"].lower()
    assert scripts["check_telemetry_freshness"]["tags"] == ["telemetry", "health"]

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

    assert (
        scripts["flag_frame_time_regressions"]["name"] == "Flag frame time regressions"
    )
    assert "frame time" in scripts["flag_frame_time_regressions"]["description"].lower()
    assert scripts["flag_frame_time_regressions"]["tags"] == [
        "rendering",
        "performance",
    ]

    assert (
        scripts["flag_render_volatility"]["name"] == "Flag render volatility hotspots"
    )
    assert "volatile" in scripts["flag_render_volatility"]["description"].lower()
    assert scripts["flag_render_volatility"]["tags"] == [
        "rendering",
        "utilisation",
    ]

    assert scripts["rebuild_unstable_caches"]["name"] == "Rebuild unstable caches"
    assert (
        "cache stability" in scripts["rebuild_unstable_caches"]["description"].lower()
    )
    assert scripts["rebuild_unstable_caches"]["tags"] == [
        "risk",
        "caches",
        "simulation",
    ]

    assert scripts["flag_render_error_streaks"]["name"] == "Flag render error streaks"
    assert "consecutive" in scripts["flag_render_error_streaks"]["description"].lower()
    assert scripts["flag_render_error_streaks"]["tags"] == [
        "rendering",
        "errors",
        "shots",
    ]

    assert scripts["explain_pnl_delta"]["name"] == "Explain P&L delta"
    assert "render spend" in scripts["explain_pnl_delta"]["description"].lower()
    assert scripts["explain_pnl_delta"]["tags"] == [
        "finance",
        "pnl",
        "insights",
    ]

    assert (
        scripts["evaluate_optimisation_playbook"]["name"]
        == "Evaluate optimisation playbook"
    )
    assert (
        "optimisation"
        in scripts["evaluate_optimisation_playbook"]["description"].lower()
    )
    assert scripts["evaluate_optimisation_playbook"]["tags"] == [
        "cost",
        "optimisation",
        "playbook",
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
        scripts["highlight_stage_bottlenecks"]["name"] == "Highlight stage bottlenecks"
    )
    assert (
        "busiest stage" in scripts["highlight_stage_bottlenecks"]["description"].lower()
    )
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


def test_wrangler_evaluate_optimisation_playbook_returns_ranked_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_breakdown = CostBreakdown(
        frame_count=DEFAULT_BASELINE_COST_INPUT.frame_count,
        gpu_hours=1280.0,
        render_hours=640.0,
        concurrency=DEFAULT_BASELINE_COST_INPUT.gpu_count,
        gpu_cost=7200.0,
        render_farm_cost=4200.0,
        storage_cost=410.0,
        egress_cost=190.0,
        misc_cost=220.0,
        total_cost=12220.0,
        cost_per_frame=4.55,
        currency=DEFAULT_BASELINE_COST_INPUT.currency,
    )

    captured: dict[str, Any] = {}

    class DummyEngine:
        baseline_cost_input = DEFAULT_BASELINE_COST_INPUT

        def run_optimization_backtest(
            self, scenarios: Any
        ) -> tuple[CostBreakdown, tuple[OptimizationResult, ...]]:
            captured["scenarios"] = scenarios
            return (
                baseline_breakdown,
                (
                    OptimizationResult(
                        name=scenarios[0].name,
                        total_cost=11270.0,
                        cost_per_frame=4.19,
                        gpu_hours=1180.0,
                        render_hours=620.0,
                        savings_vs_baseline=950.0,
                        savings_percent=7.77,
                        notes="Reduced concurrency",
                    ),
                    OptimizationResult(
                        name=scenarios[1].name,
                        total_cost=10487.0,
                        cost_per_frame=3.90,
                        gpu_hours=1200.0,
                        render_hours=610.0,
                        savings_vs_baseline=1733.0,
                        savings_percent=14.18,
                        notes="Cheaper GPU rate",
                    ),
                    OptimizationResult(
                        name=scenarios[2].name,
                        total_cost=11540.0,
                        cost_per_frame=4.29,
                        gpu_hours=1140.0,
                        render_hours=600.0,
                        savings_vs_baseline=680.0,
                        savings_percent=5.56,
                        notes="Dialled back sampling",
                    ),
                ),
            )

    dummy_engine = DummyEngine()
    monkeypatch.setattr(dashboard_module, "get_engine", lambda: dummy_engine)

    response = client.post("/wrangler/scripts/evaluate_optimisation_playbook")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "evaluate_optimisation_playbook"
    assert payload["status"] == "success"

    body = payload["payload"]
    baseline = body["baseline"]
    assert baseline["total_cost"] == pytest.approx(12220.0, rel=0, abs=0.01)
    assert baseline["render_hours"] == pytest.approx(640.0, rel=0, abs=0.01)
    assert baseline["gpu_hours"] == pytest.approx(1280.0, rel=0, abs=0.01)

    scenarios = body["scenarios"]
    assert len(scenarios) == 3
    amounts = [item["savings"]["amount"] for item in scenarios]
    assert amounts == sorted(amounts, reverse=True)

    names_from_payload = {item["name"] for item in scenarios}
    names_from_scenarios = {scenario.name for scenario in captured["scenarios"]}
    assert names_from_payload == names_from_scenarios

    leader = scenarios[0]
    formatted_amount = f"{leader['savings']['amount']:,.2f}"
    assert leader["name"] in payload["message"]
    assert formatted_amount in payload["message"]


def test_wrangler_check_telemetry_freshness_reports_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp = (datetime.utcnow() - timedelta(minutes=10)).replace(microsecond=0)
    summary = {
        "total_samples": 12,
        "averages": {},
        "sequences": [],
        "latest_sample": {
            "sequence": "SQ99",
            "shot_id": "SQ99_SH001",
            "timestamp": timestamp.isoformat(),
        },
    }

    dummy_engine = object()
    monkeypatch.setattr(dashboard_module, "get_engine", lambda: dummy_engine)
    monkeypatch.setattr(
        dashboard_module,
        "metrics_summary",
        lambda engine: summary,
    )

    response = client.post("/wrangler/scripts/check_telemetry_freshness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "check_telemetry_freshness"
    assert payload["status"] == "success"
    assert "minute" in payload["message"].lower()

    body = payload["payload"]
    assert body["latest_sequence"] == "SQ99"
    assert body["latest_shot"] == "SQ99_SH001"
    assert body["latest_timestamp"] == timestamp.isoformat()
    assert body["status"] == "healthy"
    assert body["age_minutes"] is not None
    assert body["thresholds"] == {"healthy_minutes": 30.0, "stale_minutes": 120.0}


def test_wrangler_check_telemetry_freshness_handles_missing_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = {
        "total_samples": 0,
        "averages": {},
        "sequences": [],
        "latest_sample": None,
    }

    dummy_engine = object()
    monkeypatch.setattr(dashboard_module, "get_engine", lambda: dummy_engine)
    monkeypatch.setattr(
        dashboard_module,
        "metrics_summary",
        lambda engine: summary,
    )

    response = client.post("/wrangler/scripts/check_telemetry_freshness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "check_telemetry_freshness"
    assert payload["status"] == "error"
    assert "telemetry" in payload["message"].lower()

    body = payload["payload"]
    assert body["latest_sequence"] is None
    assert body["latest_shot"] is None
    assert body["latest_timestamp"] is None
    assert body["age_minutes"] is None
    assert body["status"] is None
    assert body["thresholds"] == {"healthy_minutes": 30.0, "stale_minutes": 120.0}


def test_wrangler_audit_telemetry_coverage_classifies_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    telemetry = (
        ShotTelemetry(
            sequence="SQ10",
            shot_id="SH010",
            average_frame_time_ms=150.0,
            fps=24.0,
            error_rate=0.02,
            cache_stability=0.85,
            frames_rendered=480,
            deadline=now + timedelta(days=1),
        ),
        ShotTelemetry(
            sequence="SQ20",
            shot_id="SH020",
            average_frame_time_ms=162.0,
            fps=24.0,
            error_rate=0.04,
            cache_stability=0.7,
            frames_rendered=512,
            deadline=now + timedelta(days=2),
        ),
        ShotTelemetry(
            sequence="SQ30",
            shot_id="SH030",
            average_frame_time_ms=175.0,
            fps=24.0,
            error_rate=0.03,
            cache_stability=0.6,
            frames_rendered=450,
            deadline=now + timedelta(days=3),
        ),
        ShotTelemetry(
            sequence="SQ40",
            shot_id="SH040",
            average_frame_time_ms=140.0,
            fps=24.0,
            error_rate=0.01,
            cache_stability=0.9,
            frames_rendered=400,
            deadline=now + timedelta(days=4),
        ),
    )

    healthy_last = now - timedelta(minutes=5)
    warning_last = now - timedelta(minutes=75)
    stale_last = now - timedelta(minutes=240)

    metrics = (
        EngineRenderMetric(
            sequence="SQ10",
            shot_id="SH010",
            timestamp=healthy_last - timedelta(minutes=10),
            fps=24.0,
            frame_time_ms=150.0,
            error_count=0,
            gpu_utilisation=0.72,
            cache_health=0.9,
        ),
        EngineRenderMetric(
            sequence="SQ10",
            shot_id="SH010",
            timestamp=healthy_last,
            fps=24.0,
            frame_time_ms=148.0,
            error_count=0,
            gpu_utilisation=0.74,
            cache_health=0.9,
        ),
        EngineRenderMetric(
            sequence="SQ20",
            shot_id="SH020",
            timestamp=warning_last,
            fps=24.0,
            frame_time_ms=160.0,
            error_count=1,
            gpu_utilisation=0.65,
            cache_health=0.8,
        ),
        EngineRenderMetric(
            sequence="SQ30",
            shot_id="SH030",
            timestamp=stale_last,
            fps=24.0,
            frame_time_ms=172.0,
            error_count=2,
            gpu_utilisation=0.6,
            cache_health=0.7,
        ),
    )

    class DummyEngine:
        _telemetry = telemetry

        def stream_render_metrics(self) -> tuple[EngineRenderMetric, ...]:
            return metrics

    monkeypatch.setattr(dashboard_module, "get_engine", lambda: DummyEngine())

    response = client.post("/wrangler/scripts/audit_telemetry_coverage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "audit_telemetry_coverage"
    assert payload["status"] == "success"
    assert "telemetry attention" in payload["message"].lower()

    body = payload["payload"]
    assert body["summary"] == payload["message"]
    assert body["attention_total"] == 3
    assert body["counts"] == {"healthy": 1, "warning": 1, "stale": 1, "missing": 1}
    assert body["thresholds"] == {"healthy_minutes": 30.0, "stale_minutes": 120.0}

    shots = {
        (
            entry["sequence"],
            entry["shot"],
        ): entry
        for entry in body["shots"]
    }

    healthy = shots[("SQ10", "SH010")]
    warning = shots[("SQ20", "SH020")]
    stale = shots[("SQ30", "SH030")]
    missing = shots[("SQ40", "SH040")]

    assert healthy["status"] == "healthy"
    assert healthy["samples"] == 2
    assert healthy["telemetry_present"] is True
    assert healthy["last_seen"] == healthy_last.isoformat()
    assert healthy["age_minutes"] == pytest.approx(5.0, abs=1.0)

    assert warning["status"] == "warning"
    assert warning["samples"] == 1
    assert warning["last_seen"] == warning_last.isoformat()
    assert warning["age_minutes"] == pytest.approx(75.0, abs=1.0)

    assert stale["status"] == "stale"
    assert stale["samples"] == 1
    assert stale["last_seen"] == stale_last.isoformat()
    assert stale["age_minutes"] == pytest.approx(240.0, abs=1.5)

    assert missing["status"] == "missing"
    assert missing["samples"] == 0
    assert missing["telemetry_present"] is True
    assert missing["last_seen"] is None
    assert missing["age_minutes"] is None


def test_wrangler_audit_telemetry_coverage_handles_empty_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyEngine:
        _telemetry: tuple[Any, ...] = ()

        def stream_render_metrics(self) -> tuple[EngineRenderMetric, ...]:
            return ()

    monkeypatch.setattr(dashboard_module, "get_engine", lambda: DummyEngine())

    response = client.post("/wrangler/scripts/audit_telemetry_coverage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "audit_telemetry_coverage"
    assert payload["status"] == "success"
    assert "no telemetry" in payload["message"].lower()

    body = payload["payload"]
    assert body["summary"] == payload["message"]
    assert body["shots"] == []
    assert body["counts"] == {"healthy": 0, "warning": 0, "stale": 0, "missing": 0}
    assert body["attention_total"] == 0
    assert body["thresholds"] == {"healthy_minutes": 30.0, "stale_minutes": 120.0}


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


def test_wrangler_flag_frame_time_regressions_reports_sequences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Baseline:
        average_frame_time_ms = 40.0

    class _Engine:
        def __init__(self) -> None:
            self.baseline_cost_input = _Baseline()
            self.frame_time_regression_threshold = 0.1

    summary = {
        "total_samples": 12,
        "averages": {},
        "sequences": [
            {
                "sequence": "SQ10",
                "shots": 8,
                "avg_frame_time_ms": 45.0,
                "avg_gpu_utilisation": 0.92,
            },
            {
                "sequence": "SQ20",
                "shots": 5,
                "avg_frame_time_ms": 42.0,
                "avg_gpu_utilisation": 0.58,
            },
        ],
        "latest_sample": None,
    }

    engine = _Engine()
    monkeypatch.setattr(dashboard_module, "get_engine", lambda: engine)
    monkeypatch.setattr(
        dashboard_module,
        "metrics_summary",
        lambda engine: summary,
    )

    response = client.post("/wrangler/scripts/flag_frame_time_regressions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "flag_frame_time_regressions"
    assert payload["status"] == "success"
    assert "regression" in payload["message"].lower()
    assert "SQ10" in payload["message"]

    body = payload["payload"]
    assert body["baseline_frame_time_ms"] == pytest.approx(40.0, rel=0, abs=0.001)
    assert body["threshold_percentage"] == pytest.approx(10.0, rel=0, abs=0.01)
    assert body["regression_count"] == 1
    assert len(body["regressions"]) == 1

    regression = body["regressions"][0]
    assert regression["sequence"] == "SQ10"
    assert regression["avg_frame_time_ms"] == pytest.approx(45.0, rel=0, abs=0.001)
    assert regression["delta_percentage"] == pytest.approx(12.5, rel=0, abs=0.1)
    assert regression["utilisation_context"].startswith("High GPU load")
    assert (
        "GPU" in regression["recommendation"]
        or "profil" in regression["recommendation"].lower()
    )


def test_wrangler_flag_frame_time_regressions_reports_healthy_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Baseline:
        average_frame_time_ms = 40.0

    class _Engine:
        def __init__(self) -> None:
            self.baseline_cost_input = _Baseline()

    summary = {
        "total_samples": 6,
        "averages": {},
        "sequences": [
            {
                "sequence": "SQ10",
                "shots": 4,
                "avg_frame_time_ms": 43.5,
                "avg_gpu_utilisation": 0.65,
            },
            {
                "sequence": "SQ12",
                "shots": 3,
                "avg_frame_time_ms": 42.0,
                "avg_gpu_utilisation": 0.47,
            },
        ],
        "latest_sample": None,
    }

    engine = _Engine()
    monkeypatch.setattr(dashboard_module, "get_engine", lambda: engine)
    monkeypatch.setattr(
        dashboard_module,
        "metrics_summary",
        lambda engine: summary,
    )

    response = client.post("/wrangler/scripts/flag_frame_time_regressions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "flag_frame_time_regressions"
    assert payload["status"] == "success"
    assert "healthy" in payload["message"].lower()

    body = payload["payload"]
    assert body["regressions"] == []
    assert body["regression_count"] == 0
    assert body["threshold_percentage"] == pytest.approx(10.0, rel=0, abs=0.01)


def test_wrangler_flag_render_volatility_script_surfaces_hotspots() -> None:
    response = client.post("/wrangler/scripts/flag_render_volatility")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "flag_render_volatility"
    assert payload["status"] == "success"
    assert "volatility" in payload["message"].lower()

    body = payload["payload"]
    hotspots = body["volatility"]
    assert hotspots

    top = hotspots[0]
    assert top["drivers"]
    assert any("Render time volatility" in driver for driver in top["drivers"])
    assert isinstance(top["recommended_follow_up"], str)
    assert "profile" in top["recommended_follow_up"].lower()

    variance = top["variance"]
    assert isinstance(variance["sample_count"], int)
    assert variance["average_frame_time_ms"] >= 0
    assert "coefficient_of_variation" in variance


def test_wrangler_flag_render_error_streaks_script_ranks_streaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc)

    def metric(
        sequence: str,
        shot: str,
        minutes: int,
        *,
        errors: int,
        fps: float = 24.0,
    ) -> EngineRenderMetric:
        return EngineRenderMetric(
            sequence=sequence,
            shot_id=shot,
            timestamp=base + timedelta(minutes=minutes),
            fps=fps,
            frame_time_ms=42.0,
            error_count=errors,
            gpu_utilisation=0.75,
            cache_health=0.9,
        )

    streak_samples = [
        metric("SQ10", "SH100", 0, errors=0),
        metric("SQ07", "SH050", 5, errors=1),
        metric("SQ10", "SH100", 1, errors=1),
        metric("SQ07", "SH050", 6, errors=0),
        metric("SQ10", "SH100", 2, errors=1),
        metric("SQ05", "SH010", 4, errors=0),
        metric("SQ10", "SH100", 3, errors=1),
        metric("SQ05", "SH010", 6, errors=0),
        metric("SQ05", "SH010", 7, errors=0),
    ]

    streak_engine = Mock()
    streak_engine.stream_render_metrics.return_value = streak_samples

    monkeypatch.setattr(dashboard_module, "get_engine", lambda: streak_engine)

    response = client.post("/wrangler/scripts/flag_render_error_streaks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "flag_render_error_streaks"
    assert payload["status"] == "success"
    assert "Worst streak" in payload["message"]

    body = payload["payload"]
    assert body["summary"] == payload["message"]

    streaks = body["streaks"]
    assert [entry["longest_error_streak"] for entry in streaks] == [3, 1, 0]

    leader = streaks[0]
    assert leader["sequence"] == "SQ10"
    assert leader["shot"] == "SH100"
    assert leader["longest_error_streak"] == 3
    assert leader["sample_count"] == 4
    assert leader["recommendation"].startswith("Escalate to the render wrangler")
    assert leader["last_timestamp"].endswith("+00:00")

    tail = streaks[-1]
    assert tail["longest_error_streak"] == 0
    assert tail["recommendation"].startswith("All clear")

    streak_engine.stream_render_metrics.assert_called_once_with()

    clear_samples = [
        metric("SQ01", "SH001", 0, errors=0),
        metric("SQ02", "SH002", 1, errors=0),
    ]

    clear_engine = Mock()
    clear_engine.stream_render_metrics.return_value = clear_samples

    monkeypatch.setattr(dashboard_module, "get_engine", lambda: clear_engine)

    response = client.post("/wrangler/scripts/flag_render_error_streaks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"].startswith("All clear")

    body = payload["payload"]
    assert body["summary"] == payload["message"]
    assert all(entry["longest_error_streak"] == 0 for entry in body["streaks"])

    clear_engine.stream_render_metrics.assert_called_once_with()


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


def test_wrangler_identify_unowned_shots_flags_missing_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2024, 5, 21, 9, 0, tzinfo=timezone.utc)

    lifecycles = (
        ShotLifecycle(
            sequence="SQ50",
            shot_id="SQ50_SH010",
            stages=(
                ShotLifecycleStage(
                    name="layout",
                    started_at=base - timedelta(days=4),
                    completed_at=base - timedelta(days=2),
                    metrics={"owner": "H. Ortiz"},
                ),
                ShotLifecycleStage(
                    name="comp",
                    started_at=base - timedelta(days=1, hours=6),
                    completed_at=None,
                    metrics={"status": "Awaiting lighting plates"},
                ),
            ),
        ),
        ShotLifecycle(
            sequence="SQ60",
            shot_id="SQ60_SH020",
            stages=(
                ShotLifecycleStage(
                    name="sim",
                    started_at=base - timedelta(days=3),
                    completed_at=base - timedelta(days=1),
                    metrics={"owner": "P. Singh"},
                ),
                ShotLifecycleStage(
                    name="lighting",
                    started_at=base - timedelta(hours=12),
                    completed_at=None,
                    metrics={"lead": "B. Taylor"},
                ),
            ),
        ),
    )

    class _LifecycleEngine:
        def __init__(self, lifecycles: tuple[ShotLifecycle, ...]) -> None:
            self._lifecycles = lifecycles

        def shot_lifecycle(self) -> tuple[ShotLifecycle, ...]:
            return self._lifecycles

    monkeypatch.setattr(
        dashboard_module, "get_engine", lambda: _LifecycleEngine(lifecycles)
    )

    response = client.post("/wrangler/scripts/identify_unowned_shots")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "identify_unowned_shots"
    assert payload["status"] == "success"
    assert "missing assignments" in payload["message"].lower()

    body = payload["payload"]
    assert body["summary"] == payload["message"]
    assert body["total_unassigned"] == 1

    shots = body["shots"]
    assert len(shots) == 1
    flagged = shots[0]
    assert flagged["sequence"] == "SQ50"
    assert flagged["shot"] == "SQ50_SH010"
    assert flagged["current_stage"].lower() == "comp"
    assert flagged["stage_started_at"].endswith("+00:00")
    assert flagged["suggested_follow_up"].lower().startswith("assign comp")


def test_wrangler_identify_unowned_shots_handles_fully_assigned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2024, 5, 22, 10, 0, tzinfo=timezone.utc)

    lifecycles = (
        ShotLifecycle(
            sequence="SQ10",
            shot_id="SQ10_SH030",
            stages=(
                ShotLifecycleStage(
                    name="layout",
                    started_at=base - timedelta(days=5),
                    completed_at=base - timedelta(days=3),
                    metrics={"owner": "A. Malik"},
                ),
                ShotLifecycleStage(
                    name="comp",
                    started_at=base - timedelta(days=1),
                    completed_at=None,
                    metrics={"supervisor": "C. Bennett"},
                ),
            ),
        ),
    )

    class _LifecycleEngine:
        def __init__(self, lifecycles: tuple[ShotLifecycle, ...]) -> None:
            self._lifecycles = lifecycles

        def shot_lifecycle(self) -> tuple[ShotLifecycle, ...]:
            return self._lifecycles

    monkeypatch.setattr(
        dashboard_module, "get_engine", lambda: _LifecycleEngine(lifecycles)
    )

    response = client.post("/wrangler/scripts/identify_unowned_shots")

    assert response.status_code == 200
    payload = response.json()
    assert payload["script_id"] == "identify_unowned_shots"
    assert payload["status"] == "success"
    assert "all active shots" in payload["message"].lower()

    body = payload["payload"]
    assert body["summary"] == payload["message"]
    assert body["total_unassigned"] == 0
    assert body["shots"] == []
