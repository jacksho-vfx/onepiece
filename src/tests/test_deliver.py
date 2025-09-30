"""Tests for the ShotGrid delivery CLI."""

from __future__ import annotations

import json
import zipfile
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apps.onepiece import app as onepiece_app

deliver_module = import_module("apps.onepiece.shotgrid.deliver")

runner = CliRunner()


class StubShotgridClient:
    """Return canned approved versions for the CLI."""

    def __init__(self, versions: list[dict[str, Any]]) -> None:
        self._versions = versions
        self.requested: tuple[str, list[str] | None] | None = None

    def get_approved_versions(
        self, project_name: str, episodes: list[str] | None = None
    ) -> list[dict[str, Any]]:
        self.requested = (project_name, episodes)
        return self._versions


def _invoke_cli(args: list[str]) -> Any:
    return runner.invoke(onepiece_app.app, ["shotgrid", "deliver", *args])


def test_deliver_packages_versions_and_uploads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    monkeypatch.setattr(deliver_module, "ShotgridClient", lambda: stub_client)

    sync_calls: list[tuple[Path, str]] = []
    uploaded_snapshots: list[set[str]] = []

    def _fake_sync(source_dir: Path, destination: str, **kwargs: Any) -> None:
        snapshot = {path.name for path in Path(source_dir).iterdir()}
        uploaded_snapshots.append(snapshot)
        sync_calls.append((Path(source_dir), destination))
        progress_callback = kwargs.get("progress_callback")
        if progress_callback is not None:
            progress_callback("queued delivery.zip")

    monkeypatch.setattr(deliver_module, "s5_sync", _fake_sync)

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

    assert result.exit_code == 0, result.stdout
    assert output.exists()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "manifest.csv" in names
        delivery_name = "SHOW_EP01_SC001_SH010_COMP_v003.mov"
        assert delivery_name in names
        manifest_data = json.loads(archive.read("manifest.json"))
        assert manifest_data["delivery_path"] == delivery_name
        assert manifest_data["source_path"] == str(source)
        assert manifest_data["version"] == 3

    assert stub_client.requested == ("One Piece", None)
    assert sync_calls
    assert uploaded_snapshots
    assert uploaded_snapshots[0] == {"delivery.zip"}
    assert sync_calls[0][1] == "s3://vendor_out/One_Piece"


def test_deliver_exits_with_missing_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    monkeypatch.setattr(deliver_module, "ShotgridClient", lambda: stub_client)

    sync_invocations: list[tuple[Path, str]] = []

    def _never_called(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - safety
        sync_invocations.append((Path(args[0]), kwargs.get("destination", "")))

    monkeypatch.setattr(deliver_module, "s5_sync", _never_called)

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
    assert not sync_invocations


def test_deliver_writes_external_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
    monkeypatch.setattr(deliver_module, "ShotgridClient", lambda: stub_client)

    sync_calls: list[tuple[Path, str]] = []
    uploaded_snapshots: list[set[str]] = []

    def _fake_sync(source_dir: Path, destination: str, **_: Any) -> None:
        snapshot = {path.name for path in Path(source_dir).iterdir()}
        uploaded_snapshots.append(snapshot)
        sync_calls.append((Path(source_dir), destination))

    monkeypatch.setattr(deliver_module, "s5_sync", _fake_sync)

    output = tmp_path / "delivery.zip"
    manifest_path = tmp_path / "manifests" / "delivery.json"

    result = _invoke_cli(
        [
            "--project",
            "One Piece",
            "--episodes",
            "EP02",
            "--context",
            "vendor_out",
            "--output",
            str(output),
            "--manifest",
            str(manifest_path),
        ]
    )

    assert result.exit_code == 0, result.stdout
    assert output.exists()
    assert manifest_path.exists()
    csv_path = manifest_path.with_suffix(".csv")
    assert csv_path.exists()

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert "manifest.json" not in names
        assert "manifest.csv" not in names
        assert "SHOW_EP02_SC005_SH030_LIGHT_v012.mov" in names

    assert stub_client.requested == ("One Piece", ["EP02"])
    assert sync_calls
    assert uploaded_snapshots
    assert {"delivery.zip", "delivery.json", "delivery.csv"} == uploaded_snapshots[0]
    assert sync_calls[0][1] == "s3://vendor_out/One_Piece"
    assert "Manifest written to" in result.stdout
