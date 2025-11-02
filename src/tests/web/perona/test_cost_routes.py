from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from apps.perona.web import dashboard as dashboard_module
from apps.perona.web.dashboard import app, invalidate_engine_cache
from libraries.analytics.perona.engine import DEFAULT_CURRENCY, DEFAULT_SETTINGS_PATH

client = TestClient(app)


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

    # response = client.get("/api/cost/insights")

    # assert response.status_code == 404
    # assert response.json() == {"detail": "No telemetry statistics available."}


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

    # first_signature = dashboard_module._settings_signature()
    # second_signature = dashboard_module._settings_signature()
    #
    # assert first_signature != second_signature


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
