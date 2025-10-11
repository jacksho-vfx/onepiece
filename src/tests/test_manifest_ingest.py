import json
from pathlib import Path

import pytest

from libraries.ingest import (
    Delivery,
    DeliveryManifestError,
    MediaIngestService,
    load_delivery_manifest,
)
from libraries.ingest.service import IngestReport
from libraries.shotgrid.client import ShotgridClient


class DummyUploader:
    def __init__(self) -> None:
        self.uploads: list[tuple[Path, str, str]] = []

    def upload(self, file_path: Path, bucket: str, key: str) -> None:
        self.uploads.append((file_path, bucket, key))


@pytest.fixture()
def manifest_entry(tmp_path: Path) -> Delivery:
    media_file = tmp_path / "SHOW01_ep001_sc01_0001_comp_v002.mov"
    media_file.write_bytes(b"media")
    manifest_path = tmp_path / "manifest.json"
    manifest_payload = {
        "files": [
            {
                "show": "SHOW01",
                "episode": "ep001",
                "scene": "sc01",
                "shot": "0001",
                "asset": "comp",
                "version": 2,
                "source_path": str(media_file),
                "delivery_path": media_file.name,
                "checksum": "abc123",
            }
        ]
    }
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")
    deliveries = load_delivery_manifest(manifest_path)
    return deliveries[0]


def test_load_delivery_manifest_csv(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.csv"
    manifest_path.write_text(
        "\n".join(
            [
                "show,episode,scene,shot,asset,version,source_path,delivery_path,checksum",
                "SHOW01,ep001,sc01,0001,comp,2,/tmp/source.mov,SHOW01_ep001_sc01_0001_comp_v002.mov,deadbeef",
            ]
        ),
        encoding="utf-8",
    )

    deliveries = load_delivery_manifest(manifest_path)

    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.show == "SHOW01"
    assert delivery.version == 2
    assert delivery.delivery_path.name == "SHOW01_ep001_sc01_0001_comp_v002.mov"
    assert delivery.checksum == "deadbeef"


def test_load_delivery_manifest_json(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    payload = {
        "deliveries": [
            {
                "show": "SHOW01",
                "episode": "ep001",
                "scene": "sc01",
                "shot": "0001",
                "asset": "comp",
                "version": "2",
                "source_path": "/tmp/source.mov",
                "delivery_path": "SHOW01_ep001_sc01_0001_comp_v002.mov",
            }
        ]
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    deliveries = load_delivery_manifest(manifest_path)

    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.version == 2
    assert delivery.checksum is None


def test_load_delivery_manifest_normalises_windows_paths(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    media_name = "SHOW01_ep001_sc01_0001_comp_v002.mov"
    windows_source = "\\".join(["C:", "deliveries", "source.mov"])
    windows_delivery = "\\".join(["shots", "sc01", media_name])
    payload = {
        "deliveries": [
            {
                "show": "SHOW01",
                "episode": "ep001",
                "scene": "sc01",
                "shot": "0001",
                "asset": "comp",
                "version": 2,
                "source_path": windows_source,
                "delivery_path": windows_delivery,
            }
        ]
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    deliveries = load_delivery_manifest(manifest_path)

    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.delivery_path.as_posix() == f"shots/sc01/{media_name}"
    assert delivery.delivery_path.name == media_name
    assert delivery.source_path.as_posix() == "C:/deliveries/source.mov"


def test_load_delivery_manifest_invalid(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    with pytest.raises(DeliveryManifestError):
        load_delivery_manifest(manifest_path)


def test_ingest_folder_attaches_manifest_metadata(
    tmp_path: Path, manifest_entry: Delivery
) -> None:
    folder = tmp_path / "incoming"
    folder.mkdir()
    media_path = folder / manifest_entry.delivery_path.name
    media_path.write_bytes(b"frames")

    uploader = DummyUploader()
    shotgrid = ShotgridClient()

    service = MediaIngestService(
        project_name="Demo",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        dry_run=True,
    )

    report = service.ingest_folder(
        folder,
        recursive=False,
        manifest=[manifest_entry],
    )

    assert isinstance(report, IngestReport)
    assert report.processed_count == 1
    processed = report.processed[0]
    assert processed.delivery is not None
    assert processed.delivery.checksum == "abc123"
    assert processed.media_info.shot_name == manifest_entry.shot_name
    assert any("Dry run: would upload" in warning for warning in report.warnings)


def test_ingest_folder_matches_manifest_with_windows_paths(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "incoming"
    folder.mkdir()
    media_name = "SHOW01_ep001_sc01_0001_comp_v002.mov"
    relative_dir = Path("shots") / "sc01"
    media_path = folder / relative_dir / media_name
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"frames")

    manifest_path = tmp_path / "manifest.json"
    windows_source = "\\".join(["C:", "deliveries", "source.mov"])
    windows_delivery = "\\".join(["shots", "sc01", media_name])
    manifest_payload = {
        "deliveries": [
            {
                "show": "SHOW01",
                "episode": "ep001",
                "scene": "sc01",
                "shot": "0001",
                "asset": "comp",
                "version": 2,
                "source_path": windows_source,
                "delivery_path": windows_delivery,
            }
        ]
    }
    manifest_path.write_text(json.dumps(manifest_payload), encoding="utf-8")

    uploader = DummyUploader()
    shotgrid = ShotgridClient()

    service = MediaIngestService(
        project_name="Demo",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        dry_run=True,
    )

    report = service.ingest_folder(folder, manifest=manifest_path)

    assert report.processed_count == 1
    processed = report.processed[0]
    assert processed.delivery is not None
    assert processed.delivery.delivery_path.as_posix() == (
        relative_dir / media_name
    ).as_posix()


def test_ingest_folder_rejects_manifest_mismatch(
    tmp_path: Path, manifest_entry: Delivery
) -> None:
    folder = tmp_path / "incoming"
    folder.mkdir()
    media_path = folder / manifest_entry.delivery_path.name
    media_path.write_bytes(b"frames")

    bad_manifest = Delivery(
        show="OTHER",
        episode=manifest_entry.episode,
        scene=manifest_entry.scene,
        shot=manifest_entry.shot,
        asset=manifest_entry.asset,
        version=manifest_entry.version,
        source_path=manifest_entry.source_path,
        delivery_path=manifest_entry.delivery_path,
        checksum=manifest_entry.checksum,
    )

    uploader = DummyUploader()
    shotgrid = ShotgridClient()

    service = MediaIngestService(
        project_name="Demo",
        show_code="SHOW01",
        source="vendor",
        uploader=uploader,
        shotgrid=shotgrid,
        dry_run=True,
    )

    report = service.ingest_folder(
        folder,
        recursive=False,
        manifest=[bad_manifest],
    )

    assert report.processed_count == 0
    assert report.invalid_count == 1
    assert any(
        "Manifest metadata does not match" in warning for warning in report.warnings
    )
