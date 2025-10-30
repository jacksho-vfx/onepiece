from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any, Literal

import pytest

from libraries.automation.ingest import MediaIngestService
from libraries.automation.ingest import service as ingest_service


class _StubUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str, str]] = []

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        self.uploads.append((file_path, bucket, key))


class _StubShotgrid:
    def register_version(self, **payload: Any) -> dict[str, Any]:
        return {"id": 1, "code": payload["shot_code"]}


def _write_media_files(folder: Path, count: int, size: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        name = f"SHOW01_ep001_sc01_{index:04d}_comp.mov"
        path = folder / name
        path.write_bytes(b"0" * size)


def test_worker_auto_tune_scales_with_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_BYTES_TARGET", 1024)
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_FILES_TARGET", 4)

    folder = tmp_path / "incoming"
    _write_media_files(folder, count=12, size=2048)

    service = MediaIngestService(
        project_name="Project",
        show_code="SHOW01",
        source="vendor",
        uploader=_StubUploader(),
        shotgrid=_StubShotgrid(),
        vendor_bucket="vendor",
        client_bucket="client",
        dry_run=True,
        max_workers=6,
    )

    service.ingest_folder(folder, recursive=False)

    assert service.worker_count == 6
    assert service.worker_analysis["auto_tuned"] is True


def test_worker_auto_tune_respects_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_BYTES_TARGET", 1024)
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_FILES_TARGET", 4)

    folder = tmp_path / "incoming"
    _write_media_files(folder, count=12, size=2048)

    service = MediaIngestService(
        project_name="Project",
        show_code="SHOW01",
        source="vendor",
        uploader=_StubUploader(),
        shotgrid=_StubShotgrid(),
        vendor_bucket="vendor",
        client_bucket="client",
        dry_run=True,
        max_workers=3,
    )

    service.ingest_folder(folder, recursive=False)

    assert service.worker_count == 3
    assert service.worker_analysis["auto_tuned"] is True


def test_worker_auto_tune_can_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_BYTES_TARGET", 1024)
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_FILES_TARGET", 2)

    folder = tmp_path / "incoming"
    _write_media_files(folder, count=10, size=2048)

    service = MediaIngestService(
        project_name="Project",
        show_code="SHOW01",
        source="vendor",
        uploader=_StubUploader(),
        shotgrid=_StubShotgrid(),
        vendor_bucket="vendor",
        client_bucket="client",
        dry_run=True,
        max_workers=5,
        auto_tune_workers=False,
    )

    service.ingest_folder(folder, recursive=False)

    assert service.worker_count == 5
    assert service.worker_analysis["auto_tuned"] is False


def test_async_worker_auto_tune_applies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_BYTES_TARGET", 1024)
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_FILES_TARGET", 2)

    folder = tmp_path / "incoming"
    _write_media_files(folder, count=6, size=2048)

    captured: dict[str, int] = {}

    async def _fake_run_asyncio_jobs(
        self: MediaIngestService,
        jobs: list[Any],
        checkpoint_store: Any,
    ) -> list[Any]:
        captured["workers"] = self.max_workers
        return [self._process_job(job, checkpoint_store) for job in jobs]

    monkeypatch.setattr(
        MediaIngestService,
        "_run_asyncio_jobs",
        _fake_run_asyncio_jobs,
        raising=False,
    )

    service = MediaIngestService(
        project_name="Project",
        show_code="SHOW01",
        source="vendor",
        uploader=_StubUploader(),
        shotgrid=_StubShotgrid(),
        vendor_bucket="vendor",
        client_bucket="client",
        dry_run=False,
        max_workers=4,
        use_asyncio=True,
    )

    report = service.ingest_folder(folder, recursive=False)

    assert service.worker_count == 4
    assert captured["workers"] == 4
    assert report.processed_count == 6


def test_thread_executor_uses_autotuned_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_BYTES_TARGET", 1024)
    monkeypatch.setattr(ingest_service, "AUTO_WORKER_FILES_TARGET", 2)

    folder = tmp_path / "incoming"
    _write_media_files(folder, count=8, size=2048)

    recorded: dict[str, int] = {}

    class _ThreadPoolRecorder:
        def __init__(self, *_: Any, max_workers: int, **__: Any) -> None:
            recorded["max_workers"] = max_workers

        def __enter__(self) -> "_ThreadPoolRecorder":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
            return False

        def submit(self, fn: Any, *args: Any) -> concurrent.futures.Future:  # type: ignore[type-arg]
            future: concurrent.futures.Future = concurrent.futures.Future()  # type: ignore[type-arg]
            try:
                result = fn(*args)
            except Exception as error:  # pragma: no cover - exercised in tests
                future.set_exception(error)
            else:
                future.set_result(result)
            return future

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _ThreadPoolRecorder)

    service = MediaIngestService(
        project_name="Project",
        show_code="SHOW01",
        source="vendor",
        uploader=_StubUploader(),
        shotgrid=_StubShotgrid(),
        vendor_bucket="vendor",
        client_bucket="client",
        dry_run=False,
        max_workers=5,
        use_asyncio=False,
    )

    report = service.ingest_folder(folder, recursive=False)

    assert service.worker_count == 5
    assert recorded["max_workers"] == 5
    assert report.processed_count == 8
