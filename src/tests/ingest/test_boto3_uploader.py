from pathlib import Path

from libraries.automation.ingest.service import (
    DEFAULT_UPLOAD_CHUNK_SIZE,
    DEFAULT_UPLOAD_CONCURRENCY,
    Boto3Uploader,
    MediaIngestService,
)
from libraries.integrations.shotgrid.client import ShotgridClient


class _RecordingTransferFactory:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None
        self.config: object | None = None

    def __call__(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        self.config = object()
        return self.config


class _StubS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def upload_file(
        self,
        Filename: str,
        Bucket: str,
        Key: str,
        ExtraArgs: dict[str, object] | None = None,
        Callback: None = None,
        Config: object | None = None,
    ) -> None:
        self.calls.append(
            {
                "filename": Filename,
                "bucket": Bucket,
                "key": Key,
                "config": Config,
            }
        )


def test_boto3_uploader_uses_transfer_config_defaults() -> None:
    client = _StubS3Client()
    factory = _RecordingTransferFactory()
    uploader = Boto3Uploader(client=client, transfer_config_factory=factory)

    uploader.upload(Path("file.mov"), "bucket", "key")

    assert factory.kwargs == {
        "multipart_chunksize": DEFAULT_UPLOAD_CHUNK_SIZE,
        "max_concurrency": DEFAULT_UPLOAD_CONCURRENCY,
    }
    assert client.calls[0]["config"] is factory.config


def test_media_ingest_service_configures_boto3_uploader() -> None:
    client = _StubS3Client()
    factory = _RecordingTransferFactory()
    uploader = Boto3Uploader(client=client, transfer_config_factory=factory)
    shotgrid = ShotgridClient()

    MediaIngestService(
        project_name="Project",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        vendor_bucket="vendor_in",
        client_bucket="client_in",
        upload_chunk_size=8 * 1024 * 1024,
        upload_concurrency=4,
    )

    uploader.upload(Path("file.mov"), "bucket", "key")

    assert factory.kwargs == {
        "multipart_chunksize": 8 * 1024 * 1024,
        "max_concurrency": 4,
    }
