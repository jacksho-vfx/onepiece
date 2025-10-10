import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from fastapi.testclient import TestClient

from apps.trafalgar.web.render import (
    JOB_RETENTION_HOURS_ENV,
    JOB_STORE_PATH_ENV,
    app,
    get_render_service,
)
from apps.trafalgar.web import security


def _build_headers(key: str, secret: str) -> dict[str, str]:
    settings = security.get_security_settings()
    return {
        settings.api_key_header: key,
        settings.api_secret_header: secret,
    }


def test_health_reports_history_and_pruning(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    store_path = tmp_path / "jobs.json"
    monkeypatch.setenv(JOB_STORE_PATH_ENV, str(store_path))
    monkeypatch.setenv(JOB_RETENTION_HOURS_ENV, "0.0001")  # ~0.36 seconds

    get_render_service.cache_clear()

    with TestClient(app) as client:
        headers = _build_headers("suite-key", "suite-secret")

        response = client.get("/health", headers=headers)
        payload = response.json()
        assert payload["render_history"]["history_size"] == 0
        assert payload["render_summary"]["total_jobs"] == 0
        assert payload["render_summary"]["submission_windows"]["1h"] == 0

        job_payload = {
            "dcc": "nuke",
            "scene": "/projects/example/shot.nk",
            "frames": "1-5",
            "output": "/tmp/output",
            "farm": "mock",
            "priority": 50,
            "chunk_size": 1,
            "user": "tester",
        }

        create_response = client.post("/jobs", json=job_payload, headers=headers)
        assert create_response.status_code == 201

        response = client.get("/health", headers=headers)
        payload = response.json()
        assert payload["render_history"]["history_size"] == 1
        summary = payload["render_summary"]
        assert summary["total_jobs"] == 1
        assert summary["active_jobs"] >= 0
        assert summary["by_status"]

        data = json.loads(store_path.read_text())
        assert len(data) == 1
        data[0]["created_at"] = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        store_path.write_text(json.dumps(data), encoding="utf-8")

        get_render_service.cache_clear()

        response = client.get("/health", headers=headers)
        payload = response.json()
        metrics = payload["render_history"]
        assert metrics["history_size"] == 0
        assert metrics["store"]["total_pruned"] >= 1
        assert metrics["store"]["last_pruned_count"] >= 1
        assert payload["render_summary"]["total_jobs"] == 0

    get_render_service.cache_clear()
