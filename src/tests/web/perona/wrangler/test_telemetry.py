from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.perona.web import dashboard as dashboard_module
from libraries.analytics.perona.engine import (
    RenderMetric as EngineRenderMetric,
    ShotTelemetry,
)


def test_wrangler_check_telemetry_freshness_reports_age(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, monkeypatch: pytest.MonkeyPatch
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
