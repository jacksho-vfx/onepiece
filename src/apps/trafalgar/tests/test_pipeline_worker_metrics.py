from concurrent.futures import Future

from apps.trafalgar.pipeline import PipelineOrchestrator


class _DummyWorkerPool:
    """Minimal worker pool without a discoverable max worker count."""

    def __init__(self) -> None:
        self.shutdown_called = False

    def submit(
        self, *_: object, **__: object
    ) -> Future[None]:  # pragma: no cover - not invoked
        return Future()

    def shutdown(self, *args: object, **kwargs: object) -> None:
        self.shutdown_called = True


def test_worker_pool_metrics_fall_back_to_configured_max_workers() -> None:
    pool = _DummyWorkerPool()
    orchestrator = PipelineOrchestrator(worker_pool=pool, max_workers=3)

    metrics = orchestrator.worker_pool_metrics()

    try:
        assert metrics.max_workers == 3
    finally:
        orchestrator.shutdown()
