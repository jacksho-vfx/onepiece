import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.trafalgar.web.job_store import JobStore
from apps.trafalgar.web.render import RenderJobRequest, _JobRecord


@pytest.fixture()
def job_request() -> RenderJobRequest:
    return RenderJobRequest(
        dcc="nuke",
        scene="/projects/example/shot.nk",
        frames="1-10",
        output="/tmp/output",
        farm="mock",
        priority=50,
        chunk_size=1,
        user="tester",
    )


def _record(
    job_id: str, request: RenderJobRequest, *, created_at: datetime
) -> _JobRecord:
    return _JobRecord(
        job_id=job_id,
        farm="mock",
        farm_type="mock",
        status="submitted",
        message=None,
        request=request,
        created_at=created_at,
    )


def test_job_store_reports_zero_retention(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.json", retention=timedelta(seconds=0))

    stats = store.stats.to_dict()

    assert stats["retention_seconds"] == 0


def test_job_store_prunes_expired_records(
    tmp_path: Path, job_request: RenderJobRequest
) -> None:
    path = tmp_path / "jobs.json"
    store = JobStore(path, retention=timedelta(seconds=60))

    now = datetime.now(timezone.utc)
    expired = _record("old", job_request, created_at=now - timedelta(minutes=10))
    recent = _record("new", job_request, created_at=now - timedelta(seconds=5))

    store.save([expired, recent])

    payload = json.loads(path.read_text())
    assert [entry["job_id"] for entry in payload] == ["new"]

    stats = store.stats
    assert stats.total_pruned == 1
    assert stats.last_pruned_count == 1
    assert stats.retained_records == 1
    assert stats.last_pruned_at is not None
    assert stats.last_save_at is not None


def test_job_store_prunes_on_load(
    tmp_path: Path, job_request: RenderJobRequest
) -> None:
    path = tmp_path / "jobs.json"

    now = datetime.now(timezone.utc)
    payload = [
        {
            "job_id": "stale",
            "farm": "mock",
            "farm_type": "mock",
            "status": "submitted",
            "message": None,
            "request": job_request.model_dump(),
            "created_at": (now - timedelta(hours=5)).isoformat(),
        },
        {
            "job_id": "active",
            "farm": "mock",
            "farm_type": "mock",
            "status": "submitted",
            "message": None,
            "request": job_request.model_dump(),
            "created_at": (now - timedelta(minutes=1)).isoformat(),
        },
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    store = JobStore(path, retention=timedelta(hours=1))
    records = store.load()

    assert [record.job_id for record in records] == ["active"]

    rewritten = json.loads(path.read_text())
    assert [entry["job_id"] for entry in rewritten] == ["active"]

    stats = store.stats
    assert stats.total_pruned == 1
    assert stats.last_pruned_count == 1
    assert stats.retained_records == 1
    assert stats.last_rotation_at is not None


def test_job_store_skips_records_with_invalid_timestamps(
    tmp_path: Path, job_request: RenderJobRequest
) -> None:
    path = tmp_path / "jobs.json"
    payload = [
        {
            "job_id": "invalid",
            "farm": "mock",
            "farm_type": "mock",
            "status": "submitted",
            "message": None,
            "request": job_request.model_dump(),
            "created_at": "not-a-timestamp",
            "updated_at": "",  # present but empty should be ignored
        },
        {
            "job_id": "valid",
            "farm": "mock",
            "farm_type": "mock",
            "status": "submitted",
            "message": None,
            "request": job_request.model_dump(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    store = JobStore(path)
    records = store.load()

    assert [record.job_id for record in records] == ["valid"]
