from pathlib import Path

import pytest

from onepiece.ingest.service import MediaIngestService, parse_media_filename
from onepiece.shotgrid.client import ShotgridClient


class DummyUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str, str]] = []

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        self.uploads.append((file_path, bucket, key))


def test_parse_media_filename_success():
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
def test_parse_media_filename_failure(filename):
    with pytest.raises(ValueError):
        parse_media_filename(filename)


def test_ingest_service_processes_valid_files(tmp_path):
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
