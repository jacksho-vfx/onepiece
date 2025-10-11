from pathlib import Path

import pytest

from libraries.aws import s3_sync


def test_sync_to_bucket_rejects_unknown_show_type(tmp_path: Path) -> None:
    local_path = tmp_path / "upload"
    local_path.mkdir()

    with pytest.raises(ValueError) as excinfo:
        s3_sync.sync_to_bucket(
            bucket="bucket",
            show_code="SHOW",
            folder="plates",
            local_path=local_path,
            show_type="animation",  # type: ignore[arg-type]
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
            show_type="animation",  # type: ignore[arg-type]
        )

    assert "Unsupported show type" in str(excinfo.value)
