import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.trafalgar.web.ingest import (
    IngestRunProvider,
    IngestRunService,
    app,
    get_ingest_run_service,
)
from libraries.ingest.registry import IngestRunRegistry


class CountingRegistry(IngestRunRegistry):
    def __init__(self, path: Path) -> None:
        super().__init__(path=path)
        self.payload_reads = 0

    def _load_payload(self):  # type: ignore[override]
        self.payload_reads += 1
        return super()._load_payload()


def _write_registry(path: Path, runs: list[dict[str, object]]) -> None:
    path.write_text(json.dumps(runs), encoding="utf-8")


def test_registry_reuses_cached_data_for_missing_runs(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path, [])

    registry = CountingRegistry(path=registry_path)

    assert registry.get("missing") is None
    for _ in range(5):
        assert registry.get("missing") is None

    assert registry.payload_reads == 1


def test_registry_serves_cached_records_when_reload_fails(tmp_path: Path, monkeypatch) -> None:
    registry_path = tmp_path / "registry.json"
    _write_registry(
        registry_path,
        [
            {
                "id": "run-1",
                "started_at": "2024-02-01T12:00:00Z",
                "completed_at": "2024-02-01T12:05:00Z",
                "report": {"processed": [], "invalid": []},
            }
        ],
    )

    registry = IngestRunRegistry(path=registry_path)
    record = registry.get("run-1")
    assert record is not None

    # Simulate an in-progress writer updating the file with incomplete JSON.
    registry_path.write_text("{", encoding="utf-8")  # invalid payload, updates mtime

    def _failing_load(*args, **kwargs):
        raise json.JSONDecodeError("err", "doc", 0)

    monkeypatch.setattr("libraries.ingest.registry.json.load", _failing_load)

    assert registry.get("run-1") is record


def test_ingest_api_caches_repeated_missing_requests(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.json"
    _write_registry(registry_path, [])

    registry = CountingRegistry(path=registry_path)
    provider = IngestRunProvider(registry=registry)
    service = IngestRunService(provider=provider)

    app.dependency_overrides[get_ingest_run_service] = lambda: service
    client = TestClient(app)

    for _ in range(5):
        response = client.get("/runs/not-here")
        assert response.status_code == 404

    assert registry.payload_reads == 1

    app.dependency_overrides.clear()
