from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from libraries.delivery import manifest


@pytest.fixture()
def sample_entries(tmp_path: Path) -> tuple[list[dict[str, object]], Path]:
    source = tmp_path / "comp_v002.mov"
    source.write_text("frame-one\n")
    entries = [
        {
            "show": "blob01",
            "episode": "ep101",
            "scene": "sc01",
            "shot": "0010",
            "asset": "comp",
            "version": 2,
            "source_path": str(source),
            "delivery_path": "blob01_ep101_sc01_0010_comp_v002.mov",
        }
    ]
    return entries, source


def test_compute_checksum(tmp_path: Path) -> None:
    file_path = tmp_path / "file.bin"
    file_path.write_bytes(b"hello world")

    md5_value = manifest.compute_checksum(file_path, "md5")
    sha_value = manifest.compute_checksum(file_path, "sha256")

    assert md5_value == hashlib.md5(b"hello world").hexdigest()
    assert sha_value == hashlib.sha256(b"hello world").hexdigest()


def test_write_json_manifest_creates_file_and_schema(
    sample_entries: tuple[list[dict[str, object]], Path],
    tmp_path: Path,
) -> None:
    entries, source = sample_entries
    json_path = tmp_path / "manifest.json"

    manifest.write_json_manifest(entries, json_path)

    assert json_path.exists()
    data = json.loads(json_path.read_text())
    assert "files" in data
    assert len(data["files"]) == 1
    record = data["files"][0]

    expected_checksum = manifest.compute_checksum(source)
    assert record["checksum"] == expected_checksum
    assert record["version"] == 2
    assert set(record) == {
        "show",
        "episode",
        "scene",
        "shot",
        "asset",
        "version",
        "source_path",
        "delivery_path",
        "checksum",
    }


def test_write_csv_manifest_creates_file(
    sample_entries: tuple[list[dict[str, object]], Path],
    tmp_path: Path,
) -> None:
    entries, source = sample_entries
    csv_path = tmp_path / "manifest.csv"

    manifest.write_csv_manifest(entries, csv_path)

    assert csv_path.exists()
    with csv_path.open() as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert len(rows) == 1
    row = rows[0]
    expected_checksum = manifest.compute_checksum(source)
    assert row["checksum"] == expected_checksum
    assert row["version"] == "2"


def test_get_manifest_data_returns_expected_structure(
    sample_entries: tuple[list[dict[str, object]], Path]
) -> None:
    entries, source = sample_entries
    data = manifest.get_manifest_data(entries)

    assert "files" in data
    assert len(data["files"]) == 1
    record = data["files"][0]
    assert record["checksum"] == manifest.compute_checksum(source)
    assert record["show"] == "blob01"
    assert isinstance(record["version"], int)
