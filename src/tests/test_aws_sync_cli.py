from __future__ import annotations

from pathlib import Path

from upath import UPath

from src.apps.onepiece.aws.sync_from import sync_from as sync_from_command
from src.apps.onepiece.aws.sync_to import sync_to as sync_to_command


def test_sync_from_cli_invokes_sync_helper(monkeypatch, tmp_path) -> None:
    called: dict[str, object] = {}

    def fake_sync_from_bucket(
        bucket: str,
        show_code: str,
        folder: str,
        local_path: Path,
        *,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        called.update(
            {
                "bucket": bucket,
                "show_code": show_code,
                "folder": folder,
                "local_path": Path(local_path),
                "include": include,
                "exclude": exclude,
                "dry_run": dry_run,
            }
        )

    monkeypatch.setitem(
        sync_from_command.__globals__, "sync_from_bucket", fake_sync_from_bucket
    )

    sync_from_command(
        bucket="my-bucket",
        show_code="SHOW01",
        folder="plates",
        local_path=UPath(tmp_path),
        dry_run=True,
        include=["*.exr"],
        exclude=["*.tmp"],
    )

    assert called == {
        "bucket": "my-bucket",
        "show_code": "SHOW01",
        "folder": "plates",
        "local_path": tmp_path,
        "include": ["*.exr"],
        "exclude": ["*.tmp"],
        "dry_run": True,
    }


def test_sync_to_cli_invokes_sync_helper(monkeypatch, tmp_path) -> None:
    called: dict[str, object] = {}

    def fake_sync_to_bucket(
        bucket: str,
        show_code: str,
        folder: str,
        local_path: Path,
        *,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        called.update(
            {
                "bucket": bucket,
                "show_code": show_code,
                "folder": folder,
                "local_path": Path(local_path),
                "include": include,
                "exclude": exclude,
                "dry_run": dry_run,
            }
        )

    monkeypatch.setitem(
        sync_to_command.__globals__, "sync_to_bucket", fake_sync_to_bucket
    )

    sync_to_command(
        bucket="my-bucket",
        show_code="SHOW01",
        folder="plates",
        local_path=UPath(tmp_path),
        dry_run=True,
        include=["*.mov"],
        exclude=["*.tmp"],
    )

    assert called == {
        "bucket": "my-bucket",
        "show_code": "SHOW01",
        "folder": "plates",
        "local_path": tmp_path / "plates",
        "include": ["*.mov"],
        "exclude": ["*.tmp"],
        "dry_run": True,
    }
