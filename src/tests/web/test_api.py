"""Integration smoke-tests for the Perona FastAPI surface."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.perona.engine import (
    DEFAULT_BASELINE_COST_INPUT,
    DEFAULT_CURRENCY,
    DEFAULT_PNL_BASELINE_COST,
    DEFAULT_SETTINGS_PATH,
    DEFAULT_TARGET_ERROR_RATE,
)
from apps.perona.version import PERONA_VERSION
from apps.perona.web import dashboard as dashboard_module
from apps.perona.web.dashboard import app, invalidate_engine_cache


client = TestClient(app)
KNOWN_SEQUENCES = {"SQ12", "SQ18", "SQ05", "SQ09"}


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
    assert data["by_sequence"] == [{"name": "SQ05", "shots": 1}]
    assert {shot["sequence"] for shot in data["active_shots"]} == {"SQ05"}


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
    assert "SQ05" in {shot["sequence"] for shot in data["active_shots"]}


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
