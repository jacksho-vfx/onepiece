from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from apps.perona.web import dashboard as dashboard_module
from apps.perona.web.dashboard import app
from libraries.analytics.perona.engine.engine import PeronaEngine
from libraries.analytics.perona.engine.models import RenderMetric as EngineRenderMetric
from libraries.analytics.perona.models import RenderMetric

from . import KNOWN_SEQUENCES

METRICS_TOKEN = "demo-metrics-token"
AUTH_HEADERS = {"Authorization": f"Bearer {METRICS_TOKEN}"}


@pytest.fixture(autouse=True)
def _configure_metrics_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERONA_METRICS_TOKEN", METRICS_TOKEN)


def _render_metric_payload(sequence: str, shot_id: str, offset: int) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "shot_id": shot_id,
        "timestamp": f"2024-05-20T12:30:0{offset}Z",
        "fps": 24.0 + offset,
        "frame_time_ms": 120.0 + offset,
        "error_count": offset,
        "gpuUtilisation": 0.5 + (offset * 0.01),
        "cacheHealth": 0.9,
    }


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


def test_compute_metrics_summary_empty_dataset() -> None:
    engine = PeronaEngine()
    engine._render_log = tuple()

    summary = dashboard_module.compute_metrics_summary(engine, sample_limit=50)

    assert summary["total_samples"] == 0
    assert summary["averages"] == {
        "fps": 0.0,
        "frame_time_ms": 0.0,
        "gpu_utilisation": 0.0,
        "error_count": 0.0,
    }
    assert summary["sequences"] == []
    assert summary["latest_sample"] is None


def test_compute_metrics_summary_respects_windows() -> None:
    base_time = datetime(2024, 1, 1, 12, 0, 0)
    metrics = [
        EngineRenderMetric(
            sequence="SQ01",
            shot_id="SQ01_SH010",
            timestamp=base_time + timedelta(seconds=offset),
            fps=20.0 + offset,
            frame_time_ms=100.0 + (offset * 0.5),
            error_count=offset,
            gpu_utilisation=0.5,
            cache_health=0.9,
        )
        for offset in (0, 60, 240, 300)
    ]

    engine = PeronaEngine()
    engine._render_log = tuple(metrics)

    summary = dashboard_module.compute_metrics_summary(
        engine, sample_limit=2, window_seconds=180
    )

    expected_samples = metrics[-2:]
    assert summary["total_samples"] == len(expected_samples)

    def _rounded_mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

    assert summary["averages"] == {
        "fps": _rounded_mean([sample.fps for sample in expected_samples]),
        "frame_time_ms": _rounded_mean(
            [sample.frame_time_ms for sample in expected_samples]
        ),
        "gpu_utilisation": _rounded_mean(
            [sample.gpu_utilisation for sample in expected_samples]
        ),
        "error_count": _rounded_mean(
            [float(sample.error_count) for sample in expected_samples]
        ),
    }
    assert summary["sequences"][0]["sequence"] == "SQ01"
    assert (
        summary["latest_sample"]["timestamp"]
        == expected_samples[-1].timestamp.isoformat()
    )


def test_compute_metrics_summary_honours_explicit_time_range() -> None:
    base_time = datetime(2024, 2, 1, 0, 0, 0)
    metrics = [
        EngineRenderMetric(
            sequence="SQ%02d" % (index % 2),
            shot_id=f"SHOT_{index:03d}",
            timestamp=base_time + timedelta(minutes=index * 10),
            fps=24.0 + index,
            frame_time_ms=100.0 + index,
            error_count=index % 2,
            gpu_utilisation=0.4 + (index * 0.05),
            cache_health=0.9,
        )
        for index in range(6)
    ]

    engine = PeronaEngine()
    engine._render_log = tuple(metrics)

    start_time = base_time + timedelta(minutes=10)
    end_time = base_time + timedelta(minutes=40)

    summary = dashboard_module.compute_metrics_summary(
        engine, start_time=start_time, end_time=end_time
    )

    expected = [
        sample for sample in metrics if start_time <= sample.timestamp <= end_time
    ]

    assert summary["total_samples"] == len(expected)
    assert summary["timeline"]
    assert summary["timeline"][0]["timestamp"] == expected[0].timestamp.isoformat()
    assert summary["window"]["from"] == start_time.isoformat()
    assert summary["window"]["to"] == end_time.isoformat()


def test_compute_metrics_summary_handles_large_dataset_quickly() -> None:
    engine = PeronaEngine()
    base_time = datetime(2024, 1, 1, 0, 0, 0)
    metrics = [
        EngineRenderMetric(
            sequence="SQ%02d" % (index % 5),
            shot_id=f"SQ{index % 5:02d}_SH{index:03d}",
            timestamp=base_time + timedelta(seconds=index),
            fps=18.0 + (index % 10),
            frame_time_ms=100.0 + (index % 7),
            error_count=index % 3,
            gpu_utilisation=0.4 + ((index % 4) * 0.1),
            cache_health=0.8,
        )
        for index in range(20000)
    ]
    engine._render_log = tuple(metrics)

    start = perf_counter()
    summary = dashboard_module.compute_metrics_summary(engine, sample_limit=500)
    duration = perf_counter() - start

    tail = metrics[-500:]

    def _rounded_mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 3)

    assert summary["total_samples"] == len(tail)
    assert summary["averages"] == {
        "fps": _rounded_mean([sample.fps for sample in tail]),
        "frame_time_ms": _rounded_mean([sample.frame_time_ms for sample in tail]),
        "gpu_utilisation": _rounded_mean([sample.gpu_utilisation for sample in tail]),
        "error_count": _rounded_mean([float(sample.error_count) for sample in tail]),
    }
    assert summary["latest_sample"]["timestamp"] == tail[-1].timestamp.isoformat()
    assert duration < 0.6


def test_openapi_documents_metrics_security() -> None:
    schema = client.get("/openapi.json").json()
    bearer_scheme = schema["components"]["securitySchemes"]["HTTPBearer"]
    assert bearer_scheme["type"] == "http"
    assert bearer_scheme["scheme"] == "bearer"

    metrics_security = schema["paths"]["/api/metrics"]["post"]["security"]
    live_feed_security = schema["paths"]["/render-feed/live"]["get"]["security"]

    assert {"HTTPBearer": []} in metrics_security
    assert {"HTTPBearer": []} in live_feed_security


def test_metrics_summary_documents_window_defaults() -> None:
    schema = client.get("/openapi.json").json()
    parameters = schema["paths"]["/metrics"]["get"]["parameters"]

    sample_limit_param = next(
        item for item in parameters if item["name"] == "sample_limit"
    )
    assert sample_limit_param["schema"]["default"] == 250
    assert "summarising metrics" in sample_limit_param["description"]

    window_param = next(item for item in parameters if item["name"] == "window_seconds")
    assert window_param["schema"].get("default") is None
    assert "Defaults to no time limit" in window_param["description"]


def test_metrics_summary_endpoint_respects_query_parameters() -> None:
    engine = dashboard_module.get_engine()
    samples = list(engine.stream_render_metrics())
    latest = samples[-1]
    cutoff = latest.timestamp - timedelta(minutes=5)
    expected = [sample for sample in samples if sample.timestamp >= cutoff][-2:]

    response = client.get(
        "/metrics",
        params={"sample_limit": 2, "window_seconds": 300},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 200
    payload = response.json()

    assert payload["total_samples"] == len(expected)
    assert payload["latest_sample"]["timestamp"] == expected[-1].timestamp.isoformat()


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


def test_metrics_websocket_swaps_engine_on_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _engine_with_shot(shot_id: str) -> PeronaEngine:
        class _DummyEngine:
            def __init__(self, shot_id: str) -> None:
                self._shot_id = shot_id

            def stream_render_metrics(
                self, limit: int = 30, **_: Any
            ) -> tuple[EngineRenderMetric, ...]:
                return (
                    EngineRenderMetric(
                        sequence="SQ_RELOAD",
                        shot_id=self._shot_id,
                        timestamp=datetime.utcnow(),
                        fps=24.0,
                        frame_time_ms=120.0,
                        error_count=0,
                        gpu_utilisation=0.5,
                        cache_health=1.0,
                    ),
                )

        return _DummyEngine(shot_id)  # type: ignore[return-value]

    engines = {"one": _engine_with_shot("FIRST"), "two": _engine_with_shot("SECOND")}
    cache: dict[str, object] = {"signature": ("one",), "engine": engines["one"]}

    def _fake_get_engine(refresh: bool = False) -> PeronaEngine:  # noqa: ARG001
        return cache["engine"]  # type: ignore[return-value]

    def _fake_get_engine_cache_entry() -> SimpleNamespace:
        return SimpleNamespace(engine=cache["engine"], signature=cache["signature"])

    monkeypatch.setattr(dashboard_module.dependencies, "get_engine", _fake_get_engine)
    monkeypatch.setattr(
        dashboard_module.dependencies,
        "get_engine_cache_entry",
        _fake_get_engine_cache_entry,
    )

    with client.websocket_connect("/ws/metrics", headers=AUTH_HEADERS) as websocket:
        payload_one = websocket.receive_json()
        cache["signature"] = ("two",)
        cache["engine"] = engines["two"]
        payload_two = websocket.receive_json()

    assert payload_one["shot_id"] == "FIRST"
    assert payload_two["shot_id"] == "SECOND"


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


def test_metrics_ingest_respects_max_batch_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PERONA_METRICS_MAX_BATCH", "2")
    metrics_path = tmp_path / "metrics.ndjson"
    original_store = dashboard_module._metrics_store
    dashboard_module._metrics_store = dashboard_module.RenderMetricStore(metrics_path)
    try:
        payload = {
            "metrics": [
                _render_metric_payload("SQ42", "SQ42_SH010", 0),
                _render_metric_payload("SQ42", "SQ42_SH020", 1),
                _render_metric_payload("SQ42", "SQ42_SH030", 2),
            ]
        }

        response = client.post(
            "/api/metrics",
            json=payload,
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        body = response.json()
        assert "2" in body["detail"]
        assert not metrics_path.exists()
    finally:
        dashboard_module._metrics_store = original_store


def test_metrics_ingest_allows_batches_within_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PERONA_METRICS_MAX_BATCH", "3")
    original_store = dashboard_module._metrics_store
    dashboard_module._metrics_store = dashboard_module.RenderMetricStore(
        tmp_path / "metrics.ndjson"
    )
    try:
        payload = {
            "metrics": [
                _render_metric_payload("SQ42", "SQ42_SH010", 0),
                _render_metric_payload("SQ42", "SQ42_SH020", 1),
                _render_metric_payload("SQ42", "SQ42_SH030", 2),
            ]
        }

        response = client.post(
            "/api/metrics",
            json=payload,
            headers=AUTH_HEADERS,
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        assert response.json() == {"status": "accepted", "enqueued": 3}
    finally:
        dashboard_module._metrics_store = original_store


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


def test_metrics_ingest_reports_enqueue_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _raise(*_: Any, **__: Any) -> None:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", _raise)

    payload = {"metrics": [_render_metric_payload("SQ42", "SQ42_SH010", 0)]}

    with caplog.at_level(logging.ERROR):
        response = client.post("/api/metrics", json=payload, headers=AUTH_HEADERS)

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    detail = response.json()["detail"]
    assert "Correlation ID" in detail
    assert "Unable to enqueue metrics persistence task" in detail
    assert "Failed to enqueue metrics persistence task" in caplog.text


def test_persist_metrics_logs_io_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class FailingStore:
        path = Path("/tmp/metrics.ndjson")

        def persist(self, _: Any) -> None:  # pragma: no cover - intentionally raises
            raise OSError("write failure")

    monkeypatch.setattr(dashboard_module.dependencies, "_metrics_store", FailingStore())

    with caplog.at_level(logging.ERROR):
        with pytest.raises(OSError):
            dashboard_module.persist_metrics(
                (_render_metric_payload("SQ42", "SQ42_SH010", 0),)
            )

    assert "Failed to persist render metrics" in caplog.text
