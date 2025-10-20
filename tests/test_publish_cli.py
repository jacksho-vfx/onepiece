"""Tests for the OnePiece DCC publish CLI."""

from __future__ import annotations

import sys
import types

import importlib
import typer
from typer.testing import CliRunner

if "requests" not in sys.modules:
    requests_stub = types.ModuleType("requests")

    class _Session:  # pragma: no cover - simple import stub
        pass

    requests_stub.Session = _Session  # type: ignore[attr-defined]
    sys.modules["requests"] = requests_stub

if "libraries.ftrack" not in sys.modules:
    ftrack_stub = types.ModuleType("libraries.ftrack")

    class _FtrackRestClient:  # pragma: no cover - simple import stub
        pass

    ftrack_stub.FtrackError = RuntimeError
    ftrack_stub.FtrackRestClient = _FtrackRestClient
    sys.modules["libraries.ftrack"] = ftrack_stub

for module_name in (
    "apps.onepiece.dcc.animation",
    "apps.onepiece.dcc.open_shot",
    "apps.onepiece.dcc.unreal_import",
):
    if module_name not in sys.modules:
        stub = types.ModuleType(module_name)
        stub.app = typer.Typer()  # type: ignore[attr-defined]
        sys.modules[module_name] = stub

publish_module = importlib.import_module("apps.onepiece.dcc.publish")
app = publish_module.app
from libraries.dcc.dcc_client import (
    DCCAssetStatus,
    DCCDependencyReport,
    DCCPluginStatus,
    SupportedDCC,
)


runner = CliRunner()


def test_publish_dependency_summary_handles_path_assets(monkeypatch, tmp_path):
    """Dependency summaries should render when asset entries are ``Path`` objects."""

    scene_name = "example"
    destination = tmp_path / "publish"
    destination.mkdir()

    renders = tmp_path / "renders.mov"
    renders.write_text("renders")

    previews = tmp_path / "preview.mov"
    previews.write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("{}")

    metadata = tmp_path / "metadata.json"
    metadata.write_text("{}")

    package_dir = destination / scene_name
    required_asset = package_dir / "modules" / "arnold.mod"
    present_asset = package_dir / "scripts" / "userSetup.mel"

    report = DCCDependencyReport(
        dcc=SupportedDCC.MAYA,
        plugins=DCCPluginStatus(
            required=frozenset(), available=frozenset(), missing=frozenset()
        ),
        assets=DCCAssetStatus(
            required=(required_asset,),
            present=(present_asset,),
            missing=(),
        ),
    )

    def fake_publish_scene(*_args, dependency_callback=None, **_kwargs):
        if dependency_callback is not None:
            dependency_callback(report)
        return package_dir

    monkeypatch.setattr(publish_module, "publish_scene", fake_publish_scene)

    result = runner.invoke(
        app,
        [
            "--dcc",
            "Maya",
            "--scene-name",
            scene_name,
            "--renders",
            str(renders),
            "--previews",
            str(previews),
            "--otio",
            str(otio),
            "--metadata",
            str(metadata),
            "--destination",
            str(destination),
            "--bucket",
            "test-bucket",
            "--show-code",
            "TEST",
            "--dependency-summary",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert "Dependency summary for Maya" in result.stdout
    assert str(required_asset) in result.stdout
    assert str(present_asset) in result.stdout
