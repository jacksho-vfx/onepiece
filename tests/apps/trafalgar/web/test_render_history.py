from __future__ import annotations

import json
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.trafalgar.web.job_store import JobStore
from apps.trafalgar.web.render import RenderJobRequest, RenderSubmissionService, _JobRecord


@pytest.fixture
def sample_request() -> RenderJobRequest:
    return RenderJobRequest(
        dcc="nuke",
        scene="/projects/example/shot.nk",
        frames="1-5",
        output="/tmp/output",
        farm="mock",
        priority=None,
        chunk_size=None,
        user="tester",
    )


def _make_record(job_id: str, created_at: datetime, request: RenderJobRequest) -> _JobRecord:
    return _JobRecord(
        job_id=job_id,
        farm=request.farm,
        farm_type=request.farm,
        status="queued",
        message=None,
        request=request.model_copy(deep=True),
        created_at=created_at,
    )


def test_history_limit_pruning_consistent_after_reload(
    tmp_path: Path, sample_request: RenderJobRequest
) -> None:
    store = JobStore(tmp_path / "jobs.json")

    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    records = [
        _make_record("job-1", base_time, sample_request),
        _make_record("job-2", base_time + timedelta(minutes=1), sample_request),
        _make_record("job-3", base_time + timedelta(minutes=2), sample_request),
    ]
    store.save(records)

    service = RenderSubmissionService(
        adapters={}, job_store=store, history_limit=2
    )

    assert isinstance(service._jobs, OrderedDict)
    assert list(service._jobs.keys()) == ["job-2", "job-3"]
    assert service._history_pruned_total == 1

    reloaded = store.load()
    assert [record.job_id for record in reloaded] == ["job-2", "job-3"]

    service_reloaded = RenderSubmissionService(
        adapters={}, job_store=store, history_limit=2
    )
    assert list(service_reloaded._jobs.keys()) == ["job-2", "job-3"]


class _CountingAdapter:
    def __init__(self) -> None:
        self._counter = 0

    def __call__(self, **_: object) -> dict[str, object]:
        self._counter += 1
        return {
            "job_id": f"job-{self._counter}",
            "status": "queued",
            "farm_type": "mock",
        }


def test_serialised_history_preserves_order_across_restart(
    tmp_path: Path, sample_request: RenderJobRequest
) -> None:
    store = JobStore(tmp_path / "jobs.json")
    adapter = _CountingAdapter()
    service = RenderSubmissionService(
        adapters={"mock": adapter}, job_store=store, history_limit=5
    )

    for _ in range(3):
        service.submit_job(sample_request)

    job_ids = list(service._jobs.keys())
    assert job_ids == ["job-1", "job-2", "job-3"]

    raw_payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert [entry["job_id"] for entry in raw_payload] == job_ids

    service_reloaded = RenderSubmissionService(
        adapters={"mock": adapter}, job_store=store, history_limit=5
    )
    assert list(service_reloaded._jobs.keys()) == job_ids
