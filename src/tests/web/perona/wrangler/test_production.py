from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from apps.perona.web import dashboard as dashboard_module
from libraries.analytics.perona.engine.models import (
    DEFAULT_CURRENCY,
    CostBreakdown,
    OptimizationResult,
)
from libraries.analytics.perona.engine.models import RenderMetric as EngineRenderMetric
from libraries.analytics.perona.engine.models import (
    ShotLifecycle,
    ShotLifecycleStage,
)
from libraries.analytics.perona.engine.settings import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_PNL_BASELINE_COST,
)
from libraries.analytics.perona.ml_foundations import FeatureStatistics


def test_wrangler_boost_gpu_utilisation_script_reports_recommendations(
    client: TestClient,
) -> None:
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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


def test_wrangler_analyse_cost_drivers_script_returns_summary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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


def test_wrangler_escalate_deadline_shots_script_flags_deadline_risk(
    client: TestClient,
) -> None:
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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


def test_wrangler_flag_render_volatility_script_surfaces_hotspots(
    client: TestClient,
) -> None:
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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


def test_wrangler_explain_pnl_delta_script_returns_summary(
    client: TestClient,
) -> None:
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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


def test_wrangler_rebuild_unstable_caches_script_highlights_cache_risk(
    client: TestClient,
) -> None:
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


def test_wrangler_list_failing_jobs_script_surfaces_critical_shots(
    client: TestClient,
) -> None:
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


def test_wrangler_highlight_stage_bottlenecks_script_reports_active_load(
    client: TestClient,
) -> None:
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
