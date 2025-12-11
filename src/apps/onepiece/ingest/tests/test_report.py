from pathlib import Path

from apps.onepiece.ingest.report import build_checksum_report
from libraries.automation.ingest.manifest import Delivery, load_delivery_manifest


def test_load_delivery_manifest_with_sample_assets() -> None:
    manifest_path = Path("docs/examples/delivery_manifest_assets.json")

    deliveries = load_delivery_manifest(manifest_path)

    assert len(deliveries) == 1
    delivery = deliveries[0]
    assert delivery.delivery_path.as_posix() == "assets/ingest_clip.txt"
    assert delivery.checksum == "md5:5f5312473b5df069b01546e3aeb2f9bf"


def test_checksum_report_matches_manifest(tmp_path: Path) -> None:
    asset = Path("docs/examples/assets/ingest_clip.txt")
    manifest_path = Path("docs/examples/delivery_manifest_assets.json")
    destination_root = tmp_path / "delivery"
    destination_root.mkdir()
    destination = destination_root / "assets"
    destination.mkdir()
    copied_file = destination / asset.name
    copied_file.write_bytes(asset.read_bytes())

    deliveries = load_delivery_manifest(manifest_path)
    report = build_checksum_report([destination_root], manifest_entries=deliveries)

    assert report.summary == {
        "files_scanned": 1,
        "mismatched_files": 0,
        "files_with_manifest": 1,
        "missing_manifest_entries": 0,
    }

    entry = report.files[0]
    assert entry.status == "ok"
    assert entry.expected_checksum == "md5:5f5312473b5df069b01546e3aeb2f9bf"


def test_checksum_report_detects_mismatch(tmp_path: Path) -> None:
    asset = Path("docs/examples/assets/ingest_clip.txt")
    destination_root = tmp_path / "delivery"
    destination_root.mkdir()
    destination = destination_root / "assets"
    destination.mkdir()
    copied_file = destination / asset.name
    copied_file.write_bytes(asset.read_bytes())

    deliveries = [
        Delivery(
            show="SHOW01",
            episode="ep001",
            scene="sc01",
            shot="0001",
            asset="comp",
            version=1,
            source_path=Path("assets/ingest_clip.txt"),
            delivery_path=Path("assets/ingest_clip.txt"),
            checksum="md5:0000",
        )
    ]

    report = build_checksum_report([destination_root], manifest_entries=deliveries)

    assert report.summary["mismatched_files"] == 1
    assert report.files[0].status == "mismatch"
