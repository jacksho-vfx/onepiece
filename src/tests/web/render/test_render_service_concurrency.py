import asyncio
from itertools import cycle
import threading

import pytest

from apps.trafalgar.web import render


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FlappingAdapter:
    """Adapter that cycles through statuses to trigger poller updates."""

    def __init__(self) -> None:
        self._statuses = cycle(["queued", "rendering", "completed", "rendering"])
        self._lock = threading.Lock()

    def _next_status(self) -> str:
        with self._lock:
            return next(self._statuses)

    def __call__(
        self,
        *,
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int | None,
        user: str,
        chunk_size: int | None,
    ) -> dict[str, str]:
        status = self._next_status()
        return {"job_id": "concurrency-job", "status": status, "farm_type": "mock"}

    def get_job_status(self, job_id: str) -> dict[str, str]:
        status = self._next_status()
        payload = {"job_id": job_id, "status": status, "farm_type": "mock"}
        if status == "completed":
            payload["message"] = "done"
        return payload


@pytest.mark.anyio
async def test_list_jobs_remains_stable_during_background_polling() -> None:
    adapter = FlappingAdapter()
    service = render.RenderSubmissionService(
        {"mock": adapter},
        status_poll_interval=0.01,
    )
    request = render.RenderJobRequest(
        dcc="maya",
        scene="/scenes/example.ma",
        frames="1-10",
        output="/tmp/output",
        farm="mock",
    )
    service.submit_job(request)
    service.start_background_polling()

    try:
        await asyncio.sleep(0)

        async def exercise_concurrent_listing() -> None:
            for _ in range(50):
                results = await asyncio.gather(
                    asyncio.to_thread(service.list_jobs),
                    asyncio.to_thread(service.list_jobs),
                    asyncio.to_thread(service.list_jobs),
                )
                for jobs in results:
                    assert jobs
                    assert jobs[0].job_id == "concurrency-job"
                await asyncio.sleep(0.005)

        await asyncio.wait_for(exercise_concurrent_listing(), timeout=5)
    finally:
        await service.stop_background_polling()
