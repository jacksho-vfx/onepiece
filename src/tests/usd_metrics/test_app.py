from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from apps.usd_metrics.app import app


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("USD_METRICS_DB_PATH", str(tmp_path / "metrics.db"))
    return TestClient(app)


def _event(
    dcc: str, stage: str, duration_ms: float, sequence: str, asset: str
) -> dict[str, object]:
    return {
        "dcc": dcc,
        "stage": stage,
        "duration_ms": duration_ms,
        "sequence": sequence,
        "asset": asset,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {"source": "test"},
    }


def test_ingest_and_summary(client: TestClient) -> None:
    payload = {
        "events": [
            _event("c4d", "validate", 10.5, "SQ01", "AST-1"),
            _event("c4d", "exports", 30.0, "SQ01", "AST-1"),
            _event("nuke", "publish_camera", 25.0, "SQ02", "AST-2"),
        ]
    }

    response = client.post("/events", json=payload)
    assert response.status_code == 200
    assert response.json() == {"stored": 3}

    summary = client.get("/summary").json()
    assert len(summary) == 3
    exports = next(entry for entry in summary if entry["stage"] == "exports")
    assert exports["asset"] == "AST-1"
    assert exports["samples"] == 1
    assert round(exports["total_duration_ms"], 1) == 30.0


def test_bottleneck_ordering_and_html(client: TestClient) -> None:
    payload = {
        "events": [
            _event("unreal", "import_package", 40.0, "SQ01", "AST-1"),
            _event("unreal", "import_package", 20.0, "SQ01", "AST-1"),
            _event("nuke", "publish_camera", 15.0, "SQ02", "AST-2"),
        ]
    }
    client.post("/events", json=payload)

    bottlenecks = client.get("/bottlenecks", params={"limit": 2}).json()
    assert [entry["asset"] for entry in bottlenecks] == ["AST-1", "AST-2"]
    assert bottlenecks[0]["total_duration_ms"] > bottlenecks[1]["total_duration_ms"]

    html = client.get("/").text
    assert "USD Metrics Bottlenecks" in html
    assert "AST-1" in html
    assert "AST-2" in html
