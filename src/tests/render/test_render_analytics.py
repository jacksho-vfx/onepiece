from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import pytest

from libraries.automation.render.analytics import cost_per_frame
from apps.trafalgar.web import render as render_module
from apps.trafalgar.web.render import (
    RenderJobRequest,
    RenderSubmissionService,
    _JobRecord,
)


def _request() -> RenderJobRequest:
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


def test_cost_per_frame_calculates_expected_value() -> None:
    result = cost_per_frame(
        gpu_time=1.5,
        rate_gpu=4.0,
        cpu_time=2.0,
        rate_cpu=1.25,
        storage=0.75,
        rate_storage=0.4,
    )

    assert result == pytest.approx(1.5 * 4.0 + 2.0 * 1.25 + 0.75 * 0.4)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "gpu_time": -0.1,
            "rate_gpu": 3.5,
            "cpu_time": 0.5,
            "rate_cpu": 1.0,
            "storage": 0.2,
            "rate_storage": 0.1,
        },
        {
            "gpu_time": 0.1,
            "rate_gpu": -3.5,
            "cpu_time": 0.5,
            "rate_cpu": 1.0,
            "storage": 0.2,
            "rate_storage": 0.1,
        },
        {
            "gpu_time": 0.1,
            "rate_gpu": 3.5,
            "cpu_time": -0.5,
            "rate_cpu": 1.0,
            "storage": 0.2,
            "rate_storage": 0.1,
        },
        {
            "gpu_time": 0.1,
            "rate_gpu": 3.5,
            "cpu_time": 0.5,
            "rate_cpu": -1.0,
            "storage": 0.2,
            "rate_storage": 0.1,
        },
        {
            "gpu_time": 0.1,
            "rate_gpu": 3.5,
            "cpu_time": 0.5,
            "rate_cpu": 1.0,
            "storage": -0.2,
            "rate_storage": 0.1,
        },
        {
            "gpu_time": 0.1,
            "rate_gpu": 3.5,
            "cpu_time": 0.5,
            "rate_cpu": 1.0,
            "storage": 0.2,
            "rate_storage": -0.1,
        },
    ],
)
def test_cost_per_frame_rejects_negative_inputs(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        cost_per_frame(**kwargs)


def test_update_record_tracks_status_history_and_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    record = _JobRecord(
        job_id="job-1",
        farm="mock",
        farm_type="mock",
        status="queued",
        message=None,
        request=_request(),
        created_at=base_time,
    )

    service = RenderSubmissionService(adapters={})

    running_time = base_time + timedelta(minutes=5)
    monkeypatch.setattr(render_module, "_utcnow", lambda: running_time)

    changed = service._update_record_from_result(record, {"status": "running"})
    assert changed is True
    assert record.status == "running"
    assert record.updated_at == running_time
    assert record.completed_at is None
    assert record.status_history[-1] == ("running", running_time)

    completion_time = base_time + timedelta(minutes=15)
    monkeypatch.setattr(render_module, "_utcnow", lambda: completion_time)

    changed = service._update_record_from_result(
        record, {"status": "completed", "message": "done"}
    )
    assert changed is True
    assert record.status == "completed"
    assert record.message == "done"
    assert record.updated_at == completion_time
    assert record.completed_at == completion_time
    assert record.status_history[-1] == ("completed", completion_time)


def test_render_analytics_mixed_jobs() -> None:
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    request = _request()

    job_completed = _JobRecord(
        job_id="job-complete",
        farm="mock",
        farm_type="mock",
        status="completed",
        message=None,
        request=request.model_copy(deep=True),
        created_at=base_time,
        updated_at=base_time + timedelta(minutes=15),
        completed_at=base_time + timedelta(minutes=15),
        status_history=[
            ("queued", base_time),
            ("running", base_time + timedelta(minutes=5)),
            ("completed", base_time + timedelta(minutes=15)),
        ],
    )

    job_failed = _JobRecord(
        job_id="job-failed",
        farm="tractor",
        farm_type="tractor",
        status="failed",
        message=None,
        request=request.model_copy(deep=True),
        created_at=base_time + timedelta(hours=1),
        updated_at=base_time + timedelta(hours=1, minutes=3),
        completed_at=base_time + timedelta(hours=1, minutes=3),
        status_history=[
            ("queued", base_time + timedelta(hours=1)),
            ("failed", base_time + timedelta(hours=1, minutes=3)),
        ],
    )

    job_running = _JobRecord(
        job_id="job-running",
        farm="mock",
        farm_type="mock",
        status="running",
        message=None,
        request=request.model_copy(deep=True),
        created_at=base_time + timedelta(hours=2),
        updated_at=base_time + timedelta(hours=2, minutes=2),
        status_history=[
            ("queued", base_time + timedelta(hours=2)),
            ("running", base_time + timedelta(hours=2, minutes=2)),
        ],
    )

    service = RenderSubmissionService(adapters={})
    service._jobs = OrderedDict(
        (
            job.job_id,
            job,
        )
        for job in (job_completed, job_failed, job_running)
    )

    analytics = service.get_render_analytics(now=base_time + timedelta(hours=3))

    assert analytics.total_jobs == 3

    queued = analytics.statuses["queued"]
    assert queued.count == 3
    assert queued.active == 0
    assert queued.durations.total_seconds == pytest.approx(600.0)
    assert queued.durations.average_seconds == pytest.approx(200.0)

    running = analytics.statuses["running"]
    assert running.count == 2
    assert running.active == 1
    assert running.durations.total_seconds == pytest.approx(4080.0)

    completed = analytics.statuses["completed"]
    assert completed.count == 1
    assert completed.active == 1
    assert completed.durations.total_seconds == pytest.approx(0.0)

    failed = analytics.statuses["failed"]
    assert failed.count == 1
    assert failed.active == 1
    assert failed.durations.total_seconds == pytest.approx(0.0)

    mock_adapter = analytics.adapters["mock"]
    assert mock_adapter.total_jobs == 2
    assert mock_adapter.statuses == {"completed": 1, "running": 1}
    assert mock_adapter.completed_jobs == 1
    assert mock_adapter.average_completion_seconds == pytest.approx(900.0)

    tractor_adapter = analytics.adapters["tractor"]
    assert tractor_adapter.total_jobs == 1
    assert tractor_adapter.statuses == {"failed": 1}
    assert tractor_adapter.completed_jobs == 1
    assert tractor_adapter.average_completion_seconds == pytest.approx(180.0)

    one_hour = analytics.submission_windows["1h"]
    assert one_hour.total_jobs == 1
    assert one_hour.completed_jobs == 0
    assert one_hour.average_completion_seconds is None

    six_hours = analytics.submission_windows["6h"]
    assert six_hours.total_jobs == 3
    assert six_hours.completed_jobs == 2
    assert six_hours.average_completion_seconds == pytest.approx(540.0)
