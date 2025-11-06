"""S3 uploader implementations used by the ingest workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, cast

from .checkpoint import UploadCheckpoint

DEFAULT_UPLOAD_CHUNK_SIZE = 64 * 1024 * 1024
"""Default multipart chunk size for uploads (64 MiB)."""

MIN_MULTIPART_CHUNK_SIZE = 5 * 1024 * 1024
"""Minimum chunk size accepted by S3 for multipart uploads (5 MiB)."""

DEFAULT_UPLOAD_CONCURRENCY = 10
"""Default concurrency level used by :class:`~boto3.s3.transfer.TransferConfig`."""


class S3ClientProtocol(Protocol):
    """Subset of :mod:`boto3`'s S3 client used for uploads."""

    def upload_file(
        self,
        Filename: str,
        Bucket: str,
        Key: str,
        ExtraArgs: Mapping[str, Any] | None = ...,
        Callback: Callable[[int], None] | None = ...,
        Config: object | None = ...,
    ) -> None:
        """Upload a local file to S3."""

    def head_object(self, Bucket: str, Key: str) -> Mapping[str, Any]:
        """Return metadata describing an existing object."""

    def create_multipart_upload(self, Bucket: str, Key: str) -> Mapping[str, Any]:
        """Initiate a multipart upload."""

    def upload_part(
        self,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
    ) -> Mapping[str, Any]:
        """Upload a single multipart chunk."""

    def complete_multipart_upload(
        self,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Finalize a multipart upload."""

    def abort_multipart_upload(self, Bucket: str, Key: str, UploadId: str) -> None:
        """Abort a multipart upload."""


def _create_transfer_config(**kwargs: object) -> object:
    try:
        from boto3.s3.transfer import TransferConfig
    except ImportError as exc:  # pragma: no cover - exercised in runtime
        raise RuntimeError(
            "boto3 is required for S3 uploads. Install it via 'pip install boto3'."
        ) from exc
    return TransferConfig(**kwargs)


class Boto3Uploader:
    """Concrete uploader that relies on :mod:`boto3` for S3 transfers."""

    def __init__(
        self,
        client: S3ClientProtocol | None = None,
        *,
        upload_chunk_size: int = DEFAULT_UPLOAD_CHUNK_SIZE,
        max_concurrency: int | None = None,
        transfer_config_factory: Callable[..., object] | None = None,
    ) -> None:
        if client is None:
            try:
                import boto3
            except ImportError as exc:  # pragma: no cover - exercised in runtime
                raise RuntimeError(
                    "boto3 is required for S3 uploads. Install it via 'pip install boto3'."
                ) from exc
            boto3_client = boto3.client("s3")
            client = cast(S3ClientProtocol, boto3_client)
        self._client: S3ClientProtocol = client
        self._transfer_config_factory = (
            transfer_config_factory or _create_transfer_config
        )
        self._transfer_chunk_size = self._normalise_chunk_size(upload_chunk_size)
        self._max_concurrency = self._normalise_concurrency(max_concurrency)

    @staticmethod
    def _normalise_chunk_size(value: int) -> int:
        return max(value, MIN_MULTIPART_CHUNK_SIZE)

    @staticmethod
    def _normalise_concurrency(value: int | None) -> int:
        if value is None:
            return DEFAULT_UPLOAD_CONCURRENCY
        return max(1, value)

    def configure_transfer(
        self,
        *,
        upload_chunk_size: int | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        if upload_chunk_size is not None:
            self._transfer_chunk_size = self._normalise_chunk_size(upload_chunk_size)
        if max_concurrency is None:
            self._max_concurrency = DEFAULT_UPLOAD_CONCURRENCY
        else:
            self._max_concurrency = self._normalise_concurrency(max_concurrency)

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        config = self._transfer_config_factory(
            multipart_chunksize=self._transfer_chunk_size,
            max_concurrency=self._max_concurrency,
        )
        self._client.upload_file(str(file_path), bucket, key, Config=config)

    def head_object(self, bucket: str, key: str) -> Mapping[str, Any]:
        return self._client.head_object(Bucket=bucket, Key=key)

    def upload_resumable(
        self,
        file_path: Path,
        bucket: str,
        key: str,
        checkpoint: UploadCheckpoint,
        chunk_size: int,
        progress_callback: Callable[[UploadCheckpoint], None] | None = None,
    ) -> None:
        chunk_size = max(chunk_size, MIN_MULTIPART_CHUNK_SIZE)
        upload_id = checkpoint.upload_id

        if upload_id is None:
            response = self._client.create_multipart_upload(Bucket=bucket, Key=key)
            upload_id = str(response["UploadId"])
            checkpoint.upload_id = upload_id
            if progress_callback is not None:
                progress_callback(checkpoint)

        part_number = len(checkpoint.parts) + 1
        bytes_transferred = checkpoint.bytes_transferred

        with file_path.open("rb") as handle:
            handle.seek(bytes_transferred)
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                response = self._client.upload_part(
                    Bucket=bucket,
                    Key=key,
                    PartNumber=part_number,
                    UploadId=upload_id,
                    Body=chunk,
                )
                etag = str(response.get("ETag", ""))
                checkpoint.bytes_transferred += len(chunk)
                checkpoint.parts.append((part_number, etag))
                if progress_callback is not None:
                    progress_callback(checkpoint)
                part_number += 1

        if not checkpoint.parts:
            # Fallback for tiny objects where multipart uploads are unnecessary.
            self.upload(file_path, bucket, key)
            return

        parts_payload = [
            {"ETag": etag, "PartNumber": part_number}
            for part_number, etag in checkpoint.parts
        ]

        self._client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts_payload},
        )
        checkpoint.upload_id = None
        if progress_callback is not None:
            progress_callback(checkpoint)


__all__ = [
    "Boto3Uploader",
    "DEFAULT_UPLOAD_CHUNK_SIZE",
    "DEFAULT_UPLOAD_CONCURRENCY",
    "MIN_MULTIPART_CHUNK_SIZE",
    "S3ClientProtocol",
]
