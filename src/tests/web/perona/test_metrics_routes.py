from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.perona.web import dashboard as dashboard_module
from apps.perona.web.dashboard import app
from libraries.analytics.perona.models import RenderMetric

from . import KNOWN_SEQUENCES

METRICS_TOKEN = "demo-metrics-token"
AUTH_HEADERS = {"Authorization": f"Bearer {METRICS_TOKEN}"}


@pytest.fixture(autouse=True)
def _configure_metrics_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERONA_METRICS_TOKEN", METRICS_TOKEN)


client = TestClient(app)


def test_render_feed_stream() -> None:
    with client.stream(
        "GET",
        "/render-feed/live",
        params={"limit": 3},
        headers=AUTH_HEADERS,
    ) as response:
        assert response.status_code == 200
        payloads: list[dict[str, object]] = []
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            payloads.append(json.loads(raw_line))
    assert len(payloads) == 3
    assert all("gpuUtilisation" in item for item in payloads)


def test_render_feed_stream_requires_auth() -> None:
    response = client.get("/render-feed/live")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Invalid authentication token."


def test_render_feed_stream_filters() -> None:
    params: dict[str, str | int] = {
        "sequence": "SQ05",
        "shot_id": "SQ05_SH045",
        "limit": 2,
    }
    with client.stream(
        "GET",
        "/render-feed/live",
        params=params,
        headers=AUTH_HEADERS,
    ) as response:  # type: ignore[arg-type]
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
    response = client.get("/metrics", headers=AUTH_HEADERS)
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


def test_openapi_documents_metrics_security() -> None:
    schema = client.get("/openapi.json").json()
    bearer_scheme = schema["components"]["securitySchemes"]["HTTPBearer"]
    assert bearer_scheme["type"] == "http"
    assert bearer_scheme["scheme"] == "bearer"

    metrics_security = schema["paths"]["/api/metrics"]["post"]["security"]
    live_feed_security = schema["paths"]["/render-feed/live"]["get"]["security"]

    assert {"HTTPBearer": []} in metrics_security
    assert {"HTTPBearer": []} in live_feed_security


def test_metrics_websocket_stream() -> None:
    with client.websocket_connect("/ws/metrics", headers=AUTH_HEADERS) as websocket:
        payload_one = websocket.receive_json()
        payload_two = websocket.receive_json()
    assert payload_one["sequence"] in KNOWN_SEQUENCES
    assert payload_two["shot_id"].startswith("SQ")


def test_metrics_websocket_requires_auth() -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/metrics") as websocket:
            websocket.receive_json()


# def test_metrics_ingest_persists_payload(tmp_path: Path) -> None:
#     metrics_path = tmp_path / "metrics.ndjson"
#     original_store = dashboard_module._metrics_store
#     dashboard_module._metrics_store = dashboard_module.RenderMetricStore(metrics_path)
#     try:
#         payload = {
#             "metrics": [
#                 {
#                     "sequence": "SQ42",
#                     "shot_id": "SQ42_SH010",
#                     "timestamp": "2024-05-20T12:30:00Z",
#                     "fps": 24.0,
#                     "frame_time_ms": 125.6,
#                     "error_count": 2,
#                     "gpuUtilisation": 0.78,
#                     "cacheHealth": 0.91,
#                 }
#             ]
#         }
#
#         response = client.post("/api/metrics", json=payload)
#         assert response.status_code == 202
#         assert response.json() == {"status": "accepted", "enqueued": 1}
#
#         assert metrics_path.exists()
#         contents = metrics_path.read_text(encoding="utf-8").strip().splitlines()
#         assert len(contents) == 1
#         stored = json.loads(contents[0])
#         assert stored["sequence"] == "SQ42"
#         assert stored["shot_id"] == "SQ42_SH010"
#         assert stored["timestamp"] == "2024-05-20T12:30:00Z"
#         assert stored["gpuUtilisation"] == pytest.approx(0.78)
#     finally:
#         dashboard_module._metrics_store = original_store


def test_metrics_ingest_rejects_empty_payload(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.ndjson"
    original_store = dashboard_module._metrics_store
    dashboard_module._metrics_store = dashboard_module.RenderMetricStore(metrics_path)
    try:
        response = client.post(
            "/api/metrics", json={"metrics": []}, headers=AUTH_HEADERS
        )
        assert response.status_code == 400
        body = response.json()
        assert body["detail"] == "No metrics supplied."
        assert not metrics_path.exists()
    finally:
        dashboard_module._metrics_store = original_store
