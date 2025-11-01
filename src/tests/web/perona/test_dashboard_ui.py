from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.perona.version import PERONA_VERSION
from apps.perona.web.dashboard import app, invalidate_engine_cache
from libraries.analytics.perona.engine import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_CURRENCY,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_SETTINGS_PATH,
    DEFAULT_TARGET_ERROR_RATE,
)

client = TestClient(app)

def test_dashboard_ui_root_serves_html() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"].lower()
    assert "<title>Perona Dashboard</title>" in response.text

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
