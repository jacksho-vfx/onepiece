from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from apps.trafalgar.web import ingest
from libraries.ingest.registry import IngestRunRecord
from libraries.ingest.service import IngestReport, IngestedMedia, MediaInfo


class DummyIngestProvider(ingest.IngestRunProvider):
    def __init__(self, records: list[IngestRunRecord]):
        self._records = records

    def load_recent_runs(self, limit: int | None = None):  # type: ignore[override]
        if limit is None:
            return list(self._records)
        return list(self._records)[:limit]

    def get_run(self, run_id: str):  # type: ignore[override]
        for record in self._records:
            if record.run_id == run_id:
                return record
        return None


def _make_record(run_id: str = "abc123") -> IngestRunRecord:
    report = IngestReport(
        processed=[
            IngestedMedia(
                path=Path("/mnt/incoming/show/episode/scene/shot.mov"),
                bucket="vendor_in",
                key="show/episode/scene/shot.mov",
                media_info=MediaInfo(
                    show_code="OP",
                    episode="E001",
                    scene="S001",
                    shot="SH001",
                    descriptor="final",
                    extension="mov",
                ),
            )
        ],
        invalid=[
            (Path("/mnt/incoming/invalid_file.mov"), "Descriptor must be provided in the filename")
        ],
    )
    return IngestRunRecord(
        run_id=run_id,
        started_at=datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 12, 45, tzinfo=timezone.utc),
        report=report,
    )


def test_list_runs_serialises_registry_records():
    provider = DummyIngestProvider([_make_record()])
    service = ingest.IngestRunService(provider=provider)
    app = ingest.app
    app.dependency_overrides[ingest.get_ingest_run_service] = lambda: service
    client = TestClient(app)

    response = client.get("/runs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["id"] == "abc123"
    assert payload[0]["status"] == "completed"
    assert payload[0]["report"]["processed_count"] == 1
    assert payload[0]["report"]["invalid"][0]["reason"].startswith("Descriptor")

    app.dependency_overrides.clear()


def test_get_run_returns_404_for_missing_record():
    provider = DummyIngestProvider([])
    service = ingest.IngestRunService(provider=provider)
    app = ingest.app
    app.dependency_overrides[ingest.get_ingest_run_service] = lambda: service
    client = TestClient(app)

    response = client.get("/runs/not-here")

    assert response.status_code == 404

    app.dependency_overrides.clear()

