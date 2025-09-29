from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from apps.onepiece.app import app


runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ONEPIECE_PROJECTS_ROOT", str(tmp_path))


class DummyShotGridClient:
    def __init__(self, versions: list[dict[str, object]]) -> None:
        self._versions = versions

    def get_versions_for_project(self, project_name: str) -> list[dict[str, object]]:
        return self._versions


def _patch_clients(monkeypatch: pytest.MonkeyPatch, versions: list[dict[str, object]]) -> None:
    client = DummyShotGridClient(versions)
    monkeypatch.setattr(
        "onepiece.cli.reconcile_cli.ShotGridClient.from_env",
        classmethod(lambda cls: client),
    )


def test_reconcile_all_consistent(monkeypatch: pytest.MonkeyPatch) -> None:
    sg_versions = [
        {"shot": "ep101_sc01_0010", "version_number": 1, "file_path": "/a", "status": "rev"}
    ]
    _patch_clients(monkeypatch, sg_versions)
    monkeypatch.setattr(
        "onepiece.cli.reconcile_cli.scan_project_files",
        lambda root, scope: [
            {"shot": "ep101_sc01_0010", "version": "v001", "path": str(root / "file.mov")}
        ],
    )
    monkeypatch.setattr(
        "onepiece.cli.reconcile_cli.scan_s3_context",
        lambda project, context, scope: [
            {"shot": "ep101_sc01_0010", "version": "v001", "key": f"{context}/{project}/file.mov"}
        ],
    )

    result = runner.invoke(
        app,
        ["reconcile", "--project", "Example", "--context", "vendor_in"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0
    assert "All sources are consistent" in result.stdout


def test_reconcile_reports_mismatches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sg_versions = [
        {"shot": "ep101_sc01_0010", "version_number": 2, "file_path": "/a", "status": "rev"}
    ]
    _patch_clients(monkeypatch, sg_versions)
    monkeypatch.setattr(
        "onepiece.cli.reconcile_cli.scan_project_files",
        lambda root, scope: [
            {"shot": "ep101_sc01_0010", "version": "v001", "path": str(root / "file.mov")}
        ],
    )
    monkeypatch.setattr("onepiece.cli.reconcile_cli.scan_s3_context", lambda *args, **kwargs: [])

    csv_path = tmp_path / "report.csv"
    json_path = tmp_path / "report.json"

    result = runner.invoke(
        app,
        [
            "reconcile",
            "--project",
            "Example",
            "--csv",
            str(csv_path),
            "--json",
            str(json_path),
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 1
    assert "Discrepancies detected" in result.stdout

    assert csv_path.exists()
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = list(csv.DictReader(fh))
    assert any(row["type"] == "version_mismatch" for row in reader)

    assert json_path.exists()
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert any(item["type"] == "missing_in_fs" for item in data)


def test_reconcile_shotgrid_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "onepiece.cli.reconcile_cli.ShotGridClient.from_env",
        classmethod(lambda cls: SimpleNamespace(get_versions_for_project=_raise)),
    )

    result = runner.invoke(
        app,
        ["reconcile", "--project", "Example"],
        catch_exceptions=False,
    )

    assert result.exit_code == 2
