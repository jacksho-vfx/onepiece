from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from src.apps.onepiece import app as onepiece_app
from src.apps.onepiece.cli import deliver_cli

runner = CliRunner()


class StubShotgridClient:
    def __init__(self, versions: list[dict[str, Any]]) -> None:
        self._versions = versions
        self.requested: tuple[str, list[str] | None] | None = None

    def get_approved_versions(
        self, project_name: str, episodes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        self.requested = (project_name, episodes)
        return self._versions


def _invoke_cli(args: list[str]) -> Any:
    return runner.invoke(onepiece_app.app, ["deliver", *args])


def test_deliver_packages_versions_and_uploads(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "source.mov"
    source.write_bytes(b"frame data")

    versions = [
        {
            "shot": "SHOW_EP01_SC001_SH010_COMP",
            "version": 3,
            "file_path": str(source),
            "status": "apr",
        }
    ]

    stub_client = StubShotgridClient(versions)
    monkeypatch.setattr(deliver_cli, "ShotgridClient", lambda: stub_client)

    sync_calls: list[tuple[Path, str]] = []
    uploaded_snapshots: list[set[str]] = []

    def _fake_sync(source: Path, destination: str, **_: Any) -> None:
        sync_dir = Path(source)
        uploaded_snapshots.append({path.name for path in sync_dir.iterdir()})
        sync_calls.append((sync_dir, destination))

    monkeypatch.setattr(deliver_cli, "s5_sync", _fake_sync)

    output = tmp_path / "delivery.zip"
    result = _invoke_cli(
        [
            "--project",
            "One Piece",
            "--context",
            "vendor_out",
            "--output",
            str(output),
        ]
    )

    assert result.exit_code == 0, result.output
    assert output.exists()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "SHOW_EP01_SC001_SH010_COMP_v003.mov" in names
        assert "manifest.json" in names
        manifest_data = json.loads(archive.read("manifest.json"))
        assert manifest_data[0]["delivery_path"] == "SHOW_EP01_SC001_SH010_COMP_v003.mov"
        assert manifest_data[0]["source_path"] == str(source)

    assert stub_client.requested == ("One Piece", None)
    assert sync_calls
    assert uploaded_snapshots
    assert sync_calls[0][1] == "s3://vendor_out/One_Piece"


def test_deliver_exits_with_missing_files(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing.mov"
    versions = [
        {
            "shot": "SHOW_EP01_SC001_SH010_COMP",
            "version": 7,
            "file_path": str(missing),
            "status": "apr",
        }
    ]

    stub_client = StubShotgridClient(versions)
    monkeypatch.setattr(deliver_cli, "ShotgridClient", lambda: stub_client)
    monkeypatch.setattr(deliver_cli, "s5_sync", lambda *args, **kwargs: None)

    output = tmp_path / "delivery.zip"
    result = _invoke_cli(
        [
            "--project",
            "One Piece",
            "--context",
            "client_out",
            "--output",
            str(output),
        ]
    )

    assert result.exit_code == 1
    assert not output.exists()


def test_deliver_writes_external_manifest(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "clip.mov"
    source.write_bytes(b"frames")

    versions = [
        {
            "shot": "SHOW_EP02_SC005_SH030_LIGHT",
            "version": "v12",
            "file_path": str(source),
            "status": "apr",
        }
    ]

    stub_client = StubShotgridClient(versions)
    monkeypatch.setattr(deliver_cli, "ShotgridClient", lambda: stub_client)

    sync_calls: list[tuple[Path, str]] = []
    uploaded_snapshots: list[set[str]] = []

    def _fake_sync(source: Path, destination: str, **_: Any) -> None:
        sync_dir = Path(source)
        uploaded_snapshots.append({path.name for path in sync_dir.iterdir()})
        sync_calls.append((sync_dir, destination))

    monkeypatch.setattr(deliver_cli, "s5_sync", _fake_sync)

    output = tmp_path / "delivery.zip"
    manifest_path = tmp_path / "manifests" / "delivery.json"

    result = _invoke_cli(
        [
            "--project",
            "One Piece",
            "--context",
            "vendor_out",
            "--output",
            str(output),
            "--manifest",
            str(manifest_path),
        ]
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
    assert manifest_path.exists()
    csv_path = manifest_path.with_suffix(".csv")
    assert csv_path.exists()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "manifest.json" not in names
        assert "SHOW_EP02_SC005_SH030_LIGHT_v012.mov" in names

    assert sync_calls
    assert uploaded_snapshots
    assert {"delivery.zip", "delivery.json", "delivery.csv"}.issubset(
        uploaded_snapshots[0]
    )
