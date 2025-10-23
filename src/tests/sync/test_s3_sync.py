from pathlib import Path

import pytest

from libraries.aws import s3_sync


def test_build_s3_uri_strips_extra_slashes() -> None:
    uri = s3_sync._build_s3_uri("bucket", "SHOW/", "plates/", "vendor_out")
    assert uri == "s3://bucket/vendor_out/SHOW/plates/"


@pytest.mark.parametrize("segment", ["", "/", " /// "])
def test_build_s3_uri_rejects_empty_segments(segment: str) -> None:
    with pytest.raises(ValueError):
        s3_sync._build_s3_uri("bucket", segment, "plates", "vendor_out")


@pytest.mark.parametrize("segment", ["", "/", "///"])
def test_build_s3_uri_rejects_empty_folder(segment: str) -> None:
    with pytest.raises(ValueError):
        s3_sync._build_s3_uri("bucket", "SHOW", segment, "vendor_out")


def test_sync_to_bucket_rejects_unknown_show_type(tmp_path: Path) -> None:
    local_path = tmp_path / "upload"
    local_path.mkdir()

    with pytest.raises(ValueError) as excinfo:
        s3_sync.sync_to_bucket(
            bucket="bucket",
            show_code="SHOW",
            folder="plates",
            local_path=local_path,
            show_type="animation",
        )

    assert "Unsupported show type" in str(excinfo.value)


def test_sync_from_bucket_rejects_unknown_show_type(tmp_path: Path) -> None:
    local_path = tmp_path / "download"

    with pytest.raises(ValueError) as excinfo:
        s3_sync.sync_from_bucket(
            bucket="bucket",
            show_code="SHOW",
            folder="plates",
            local_path=local_path,
            show_type="animation",
        )

    assert "Unsupported show type" in str(excinfo.value)
