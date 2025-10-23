import asyncio
import inspect
import logging
from pathlib import Path

import pytest
from unittest.mock import AsyncMock
from typing import Awaitable, cast

from libraries.automation.ingest.service import (
    IngestedMedia,
    MediaIngestService,
    ShotgridAuthenticationError,
    ShotgridConnectivityError,
    ShotgridSchemaError,
    _UploadJob,
    _UploadResult,
    parse_media_filename,
)
from libraries.integrations.shotgrid.client import (
    ShotgridClient,
    ShotgridOperationError,
    Version,
)


class DummyUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str, str]] = []

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        self.uploads.append((file_path, bucket, key))


class _RecordingShotgridClient(ShotgridClient):  # type: ignore[misc]
    def __init__(self) -> None:
        super().__init__()
        self.register_calls: list[tuple[str, Path]] = []

    def register_version(
        self,
        *,
        project_name: str,
        shot_code: str,
        file_path: Path,
        description: str | None = None,
    ) -> Version:
        self.register_calls.append((shot_code, file_path))
        return super().register_version(
            project_name=project_name,
            shot_code=shot_code,
            file_path=file_path,
            description=description,
        )


class _FailingShotgridClient:
    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    def register_version(
        self,
        *,
        project_name: str,
        shot_code: str,
        file_path: Path,
        description: str | None = None,
    ) -> dict[str, str]:
        raise self._exception


def test_parse_media_filename_success() -> None:
    info = parse_media_filename("SHOW01_ep001_sc01_0001_comp.mov")
    assert info.show_code == "SHOW01"
    assert info.shot_name == "ep001_sc01_0001"
    assert info.descriptor == "comp"
    assert info.extension == "mov"


@pytest.mark.parametrize(
    "filename",
    [
        "SHOW01_ep001_sc01_0001.mov",  # missing descriptor
        "SHOW_ep001_sc01_0001_comp.mov",  # invalid show
        "SHOW01_ep1_sc01_0001_comp.mov",  # invalid episode
    ],
)
def test_parse_media_filename_failure(filename: str) -> None:
    with pytest.raises(ValueError):
        parse_media_filename(filename)


def test_ingest_service_processes_valid_files(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    valid = incoming / "SHOW01_ep001_sc01_0001_comp.mov"
    valid.write_bytes(b"data")

    invalid = incoming / "SHOW02_ep001_sc01_0001_comp.mov"
    invalid.write_bytes(b"data")

    uploader = DummyUploader()
    shotgrid = ShotgridClient()

    service = MediaIngestService(
        project_name="CoolShow",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        vendor_bucket="vendor_in",
        client_bucket="client_in",
    )

    report = service.ingest_folder(incoming, recursive=False)

    assert report.processed_count == 1
    assert report.invalid_count == 1

    upload = uploader.uploads[0]
    assert upload[0] == valid
    assert upload[1] == "vendor_in"
    assert upload[2].endswith(valid.name)

    versions = shotgrid.list_versions()
    assert len(versions) == 1
    assert versions[0]["shot"] == "ep001_sc01_0001"
    assert versions[0]["code"] == valid.stem


def test_ingest_service_accepts_case_insensitive_show_code(tmp_path: Path) -> None:
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    valid = incoming / "SHOW01_ep001_sc01_0001_comp.mov"
    valid.write_bytes(b"data")

    uploader = DummyUploader()
    shotgrid = ShotgridClient()

    service = MediaIngestService(
        project_name="CoolShow",
        show_code="show01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        vendor_bucket="vendor_in",
        client_bucket="client_in",
    )

    report = service.ingest_folder(incoming, recursive=False)

    assert report.processed_count == 1
    assert report.invalid_count == 0


def test_ingest_service_returns_dry_run_report(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    incoming = tmp_path / "incoming"
    incoming.mkdir()

    valid = incoming / "SHOW01_ep001_sc01_0001_comp.mov"
    valid.write_bytes(b"data")

    uploader = DummyUploader()
    shotgrid = _RecordingShotgridClient()

    service = MediaIngestService(
        project_name="CoolShow",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        vendor_bucket="vendor_in",
        client_bucket="client_in",
        dry_run=True,
    )

    report = service.ingest_folder(incoming, recursive=False)

    assert report.processed_count == 1
    assert not uploader.uploads
    assert not shotgrid.register_calls
    assert any("Dry run: would upload" in warning for warning in report.warnings)
    assert any(
        "Dry run: would register ShotGrid Version" in warning
        for warning in report.warnings
    )
    assert any(
        "ingest.version_registration_skipped" in record.getMessage()
        for record in caplog.records
    )


def _prepare_ingest_folder(tmp_path: Path) -> Path:
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    valid = incoming / "SHOW01_ep001_sc01_0001_comp.mov"
    valid.write_bytes(b"data")
    return incoming


def _make_service(shotgrid: ShotgridClient) -> MediaIngestService:
    uploader = DummyUploader()
    return MediaIngestService(
        project_name="CoolShow",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        vendor_bucket="vendor_in",
        client_bucket="client_in",
    )


def test_ingest_service_raises_authentication_error(tmp_path: Path) -> None:
    incoming = _prepare_ingest_folder(tmp_path)
    service = _make_service(_FailingShotgridClient(PermissionError("invalid api key")))

    with pytest.raises(ShotgridAuthenticationError) as excinfo:
        service.ingest_folder(incoming, recursive=False)

    assert "Check the API key" in str(excinfo.value)
    assert "retry" in str(excinfo.value).lower()


def test_ingest_service_raises_schema_error(tmp_path: Path) -> None:
    incoming = _prepare_ingest_folder(tmp_path)
    service = _make_service(_FailingShotgridClient(ValueError("missing Shot entity")))

    with pytest.raises(ShotgridSchemaError) as excinfo:
        service.ingest_folder(incoming, recursive=False)

    message = str(excinfo.value)
    assert "rejected the version payload" in message
    assert "retry" in message.lower()


def test_ingest_service_raises_connectivity_error(tmp_path: Path) -> None:
    incoming = _prepare_ingest_folder(tmp_path)
    service = _make_service(
        _FailingShotgridClient(ShotgridOperationError("timed out communicating"))
    )

    with pytest.raises(ShotgridConnectivityError) as excinfo:
        service.ingest_folder(incoming, recursive=False)

    message = str(excinfo.value)
    assert "ShotGrid did not respond" in message
    assert "retry" in message.lower()


def _create_asyncio_service(tmp_path: Path) -> tuple[MediaIngestService, _UploadJob, _UploadResult]:
    path = tmp_path / "SHOW01_ep001_sc01_0001_comp.mov"
    path.write_bytes(b"data")
    media_info = parse_media_filename(path.name)

    job = _UploadJob(
        path=path,
        bucket="bucket",
        key="bucket/key",
        media_info=media_info,
        delivery=None,
        size=path.stat().st_size,
    )

    media = IngestedMedia(
        path=path,
        bucket="bucket",
        key="bucket/key",
        media_info=media_info,
        delivery=None,
    )

    result = _UploadResult(media=media, warnings=[])

    service = MediaIngestService(
        project_name="CoolShow",
        show_code="SHOW01",
        source="vendor",
        uploader=DummyUploader(),
        shotgrid=ShotgridClient(),
        use_asyncio=True,
    )

    return service, job, result


def test_execute_uploads_asyncio_outside_event_loop(tmp_path: Path) -> None:
    service, job, expected = _create_asyncio_service(tmp_path)
    mock_runner = AsyncMock(return_value=[expected])
    service._run_asyncio_jobs = mock_runner  # type: ignore[assignment]

    results = service._execute_uploads([job], None)

    assert results == [expected]
    assert mock_runner.await_count == 1


def test_execute_uploads_asyncio_inside_event_loop(tmp_path: Path) -> None:
    service, job, expected = _create_asyncio_service(tmp_path)
    mock_runner = AsyncMock(return_value=[expected])
    service._run_asyncio_jobs = mock_runner  # type: ignore[assignment]

    async def _invoke() -> None:
        maybe_coro = service._execute_uploads([job], None)

        assert inspect.isawaitable(maybe_coro)
        results = await cast(Awaitable[list[_UploadResult]], maybe_coro)

        assert results == [expected]

    asyncio.run(_invoke())
    assert mock_runner.await_count == 1
