import json
from pathlib import Path
from typing import Any

import pytest

from libraries.ingest.service import MediaIngestService, UploadCheckpoint
from libraries.shotgrid.client import ShotgridClient


class FlakyResumableUploader:
    """Uploader that fails once before allowing a resume."""

    def __init__(self) -> None:
        self.remaining_failures = 1
        self.completed: list[tuple[Path, str, str]] = []
        self.progress_updates: list[int] = []

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        checkpoint = UploadCheckpoint(
            file_path=file_path,
            bucket=bucket,
            key=key,
            file_size=file_path.stat().st_size,
        )
        self.upload_resumable(file_path, bucket, key, checkpoint, 4)

    def upload_resumable(
        self,
        file_path: Path,
        bucket: str,
        key: str,
        checkpoint: UploadCheckpoint,
        chunk_size: int,
        progress_callback: Any | None = None,
    ) -> None:
        part_number = len(checkpoint.parts) + 1
        with file_path.open("rb") as handle:
            handle.seek(checkpoint.bytes_transferred)
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                checkpoint.bytes_transferred += len(chunk)
                checkpoint.parts.append((part_number, f"etag-{part_number}"))
                if progress_callback is not None:
                    progress_callback(checkpoint)
                self.progress_updates.append(checkpoint.bytes_transferred)
                if self.remaining_failures > 0:
                    self.remaining_failures -= 1
                    raise RuntimeError("Simulated interruption")
                part_number += 1
        self.completed.append((file_path, bucket, key))


def _create_media(tmp_path: Path) -> Path:
    folder = tmp_path / "incoming"
    folder.mkdir()
    media = folder / "SHOW01_ep001_sc01_0001_comp.mov"
    media.write_bytes(b"abcdefghij")
    return folder


def test_resume_upload_recovers_from_interruption(tmp_path: Path) -> None:
    folder = _create_media(tmp_path)
    checkpoint_dir = tmp_path / "checkpoints"

    uploader = FlakyResumableUploader()
    shotgrid = ShotgridClient()

    service = MediaIngestService(
        project_name="Demo",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        resume_enabled=True,
        checkpoint_dir=checkpoint_dir,
        checkpoint_threshold_bytes=0,
        upload_chunk_size=4,
        max_workers=1,
    )

    with pytest.raises(RuntimeError):
        service.ingest_folder(folder, recursive=False)

    checkpoint_files = list(checkpoint_dir.glob("*.json"))
    assert (
        checkpoint_files
    ), "Checkpoint metadata should be written after an interruption"

    payload = json.loads(checkpoint_files[0].read_text(encoding="utf-8"))
    assert payload["bytes_transferred"] > 0
    assert payload["parts"], "Multipart progress must be persisted"

    uploader.remaining_failures = 0
    report = service.ingest_folder(folder, recursive=False)

    assert report.processed_count == 1
    assert uploader.completed
    assert not list(checkpoint_dir.glob("*.json")), "Successful runs clear checkpoints"


def test_asyncio_concurrency_handles_multiple_files(tmp_path: Path) -> None:
    folder = tmp_path / "incoming"
    folder.mkdir()
    for index in range(3):
        path = folder / f"SHOW01_ep001_sc01_{index:04d}_comp.mov"
        path.write_bytes(b"frame")

    uploader = FlakyResumableUploader()
    uploader.remaining_failures = 0
    shotgrid = ShotgridClient()

    service = MediaIngestService(
        project_name="Demo",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        resume_enabled=True,
        checkpoint_dir=tmp_path / "checkpoints",
        checkpoint_threshold_bytes=0,
        upload_chunk_size=2,
        max_workers=2,
        use_asyncio=True,
    )

    report = service.ingest_folder(folder, recursive=False)

    assert report.processed_count == 3
    assert len(uploader.completed) == 3
