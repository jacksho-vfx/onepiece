from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from apps.trafalgar.pipeline import WorkerPoolMetrics, set_pipeline_orchestrator
from apps.trafalgar.web import pipeline as pipeline_module


class _DummyStore:
    def close(self) -> None:  # pragma: no cover - test hook
        return None


class _DummyOrchestrator:
    def __init__(self, metrics: WorkerPoolMetrics) -> None:
        self._metrics = metrics
        self._store = _DummyStore()

    def worker_pool_metrics(self) -> WorkerPoolMetrics:
        return self._metrics

    def shutdown(self, *, wait: bool = True) -> None:  # pragma: no cover - test hook
        return None


@pytest.fixture()
def dashboard_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "monitoring-token"
    monkeypatch.setenv("TRAFALGAR_DASHBOARD_TOKEN", token)
    return token


@pytest.fixture()
def client(
    dashboard_token: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    class _DummyProfile:
        pipeline_storage = None

    monkeypatch.setattr(pipeline_module, "load_profile", lambda: _DummyProfile())
    monkeypatch.setattr(
        pipeline_module, "configure_orchestrator_from_profile", lambda *_, **__: None
    )

    set_pipeline_orchestrator(
        _DummyOrchestrator(WorkerPoolMetrics(max_workers=8, active_workers=3))
    )
    with TestClient(pipeline_module.app) as instance:
        yield instance
    set_pipeline_orchestrator(None)


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_reports_worker_metrics(
    client: TestClient, dashboard_token: str
) -> None:
    response = client.get("/health", headers=_auth_headers(dashboard_token))

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "workers": {"max_workers": 8, "active_workers": 3},
    }


def test_metrics_exposes_prometheus_payload(
    client: TestClient, dashboard_token: str
) -> None:
    response = client.get("/metrics", headers=_auth_headers(dashboard_token))

    assert response.status_code == 200
    body = response.text.strip().split("\n")
    assert "trafalgar_worker_active_count 3" in body
    assert "trafalgar_worker_max_count 8" in body
