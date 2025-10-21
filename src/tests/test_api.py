"""Integration tests for the Perona FastAPI dashboard surface."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.perona.version import PERONA_VERSION
from apps.perona.web import dashboard


client = TestClient(dashboard.app)


def test_health_endpoint_reports_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_exposes_perona_version() -> None:
    assert dashboard.app.version == PERONA_VERSION


def test_render_feed_endpoint_limits_results() -> None:
    response = client.get("/render-feed", params={"limit": 5})

    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 5
    assert {"sequence", "shot_id", "fps"}.issubset(data[0].keys())


def test_cost_estimate_endpoint_returns_breakdown() -> None:
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


def test_optimization_backtest_endpoint_reports_savings() -> None:
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


def test_shots_lifecycle_endpoint_returns_timelines() -> None:
    response = client.get("/shots/lifecycle")

    assert response.status_code == 200

    data = response.json()
    assert data
    assert {"sequence", "shot_id", "current_stage"}.issubset(data[0].keys())


def test_ndjson_render_feed_stream() -> None:
    async def _collect_stream() -> list[dict[str, object]]:
        def _read_stream() -> list[dict[str, object]]:
            with client.stream(
                "GET", "/render-feed/live", params={"limit": 3}
            ) as response:
                assert response.status_code == 200
                payloads: list[dict[str, object]] = []
                for raw_line in response.iter_lines():
                    if not raw_line:
                        continue
                    payloads.append(json.loads(raw_line))
            return payloads

        return await asyncio.to_thread(_read_stream)

    payloads = asyncio.run(_collect_stream())

    assert len(payloads) == 3
    assert all("gpuUtilisation" in item for item in payloads)


def test_settings_override_via_environment(tmp_path: Path) -> None:
    settings_path = tmp_path / "override.toml"
    settings_path.write_text(
        """
pnl_baseline_cost = 4321.0

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

    original_env = os.environ.get("PERONA_SETTINGS_PATH")
    os.environ["PERONA_SETTINGS_PATH"] = str(settings_path)

    try:
        reloaded = importlib.reload(dashboard)
        override_client = TestClient(reloaded.app)
        response = override_client.get("/pnl")

        assert response.status_code == 200
        data = response.json()
        assert data["baseline_cost"] == pytest.approx(4321.0)
    finally:
        if original_env is None:
            os.environ.pop("PERONA_SETTINGS_PATH", None)
        else:
            os.environ["PERONA_SETTINGS_PATH"] = original_env
        refreshed = importlib.reload(dashboard)
        global client
        client = TestClient(refreshed.app)
