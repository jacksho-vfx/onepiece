"""Integration smoke-tests for the Perona FastAPI surface."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.perona.version import PERONA_VERSION
from apps.perona.web.dashboard import app, invalidate_engine_cache


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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


def test_shots_lifecycle_endpoint() -> None:
    response = client.get("/shots/lifecycle")
    assert response.status_code == 200
    data = response.json()
    assert data
    assert {"sequence", "shot_id", "current_stage"}.issubset(data[0].keys())


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
    with client.stream("GET", "/render-feed/live", params=params) as response:
        assert response.status_code == 200
        payloads: list[dict[str, object]] = []
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            payloads.append(json.loads(raw_line))
    assert len(payloads) == 2
    assert {item["sequence"] for item in payloads} == {"SQ05"}
    assert {item["shot_id"] for item in payloads} == {"SQ05_SH045"}


def test_settings_reload_between_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings updates apply without restarting the FastAPI app."""

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
