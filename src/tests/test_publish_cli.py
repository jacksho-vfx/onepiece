"""Tests for the publish CLI entrypoint."""

import importlib
import json
from pathlib import Path
from typing import Any, TypedDict

import pytest
from typer.testing import CliRunner

from apps.onepiece.dcc.publish import app
from libraries.dcc.dcc_client import (
    DCCAssetStatus,
    DCCDependencyReport,
    DCCPluginStatus,
    SupportedDCC,
)
from libraries.dcc.maya.unreal_export_checker import UnrealExportReport

runner = CliRunner()


class Called(TypedDict, total=False):
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


def _dependency_report(dcc: SupportedDCC = SupportedDCC.NUKE) -> DCCDependencyReport:
    return DCCDependencyReport(
        dcc=dcc,
        plugins=DCCPluginStatus(
            required=frozenset({"CaraVR", "OCIO"}),
            available=frozenset({"CaraVR", "OCIO"}),
            missing=frozenset(),
        ),
        assets=DCCAssetStatus(
            required=(),
            present=(),
            missing=(),
        ),
    )


def test_publish_cli_invokes_publish_with_direct_upload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    renders = tmp_path / "renders"
    renders.mkdir()
    (renders / "beauty.exr").write_text("beauty")

    previews = tmp_path / "previews"
    previews.mkdir()
    (previews / "preview.jpg").write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("otio")

    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"shot": "010"}))

    destination = tmp_path / "package"
    destination.mkdir()

    called: Called = {}

    module = importlib.import_module("apps.onepiece.dcc.publish")

    def fake_publish_scene(*args: Any, **kwargs: Any) -> Path:
        called["args"] = args
        called["kwargs"] = kwargs
        callback = kwargs.get("dependency_callback")
        if callback is not None:
            callback(_dependency_report())
        return Path("/tmp/package")

    monkeypatch.setattr(module, "publish_scene", fake_publish_scene)

    result = runner.invoke(
        app,
        [
            "--dcc",
            "Nuke",
            "--scene-name",
            "ep01_sc01",
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
            "bucket",
            "--show-code",
            "OP",
            "--show-type",
            "vfx",
            "--profile",
            "artist-profile",
            "--direct-upload-path",
            "s3://bucket/custom/path",
            "--dependency-summary",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["args"][0] is SupportedDCC.NUKE
    assert called["kwargs"]["direct_s3_path"] == "s3://bucket/custom/path"
    assert called["kwargs"]["profile"] == "artist-profile"
    assert "Dependency summary for Nuke" in result.output
    assert "Plugins missing: None" in result.output


def test_publish_cli_dependency_summary_includes_maya_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    renders = tmp_path / "renders"
    renders.mkdir()
    (renders / "beauty.exr").write_text("beauty")

    previews = tmp_path / "previews"
    previews.mkdir()
    (previews / "preview.jpg").write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("otio")

    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"shot": "010"}))

    destination = tmp_path / "package"
    destination.mkdir()

    module = importlib.import_module("apps.onepiece.dcc.publish")

    def fake_publish_scene(*args: Any, **kwargs: Any) -> Path:
        dependency_callback = kwargs.get("dependency_callback")
        if dependency_callback is not None:
            dependency_callback(_dependency_report(SupportedDCC.MAYA))

        maya_callback = kwargs.get("maya_validation_callback")
        if maya_callback is not None:
            maya_callback(
                UnrealExportReport(
                    asset_name="SK_Hero",
                    scale_valid=True,
                    skeleton_valid=True,
                    naming_valid=True,
                    issues=(),
                )
            )
        return Path("/tmp/package")

    monkeypatch.setattr(module, "publish_scene", fake_publish_scene)

    result = runner.invoke(
        app,
        [
            "--dcc",
            "Maya",
            "--scene-name",
            "ep01_sc02",
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
            "bucket",
            "--show-code",
            "OP",
            "--dependency-summary",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Dependency summary for Maya" in result.output
    assert "Maya Unreal export validation for SK_Hero" in result.output


def test_publish_cli_validates_direct_upload_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    renders = tmp_path / "renders"
    renders.mkdir()
    (renders / "beauty.exr").write_text("beauty")

    previews = tmp_path / "previews"
    previews.mkdir()
    (previews / "preview.jpg").write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("otio")

    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"shot": "010"}))

    destination = tmp_path / "package"
    destination.mkdir()

    module = importlib.import_module("apps.onepiece.dcc.publish")
    monkeypatch.setattr(
        module, "publish_scene", lambda *args, **kwargs: Path("/tmp/package")
    )

    result = runner.invoke(
        app,
        [
            "--dcc",
            "Nuke",
            "--scene-name",
            "ep01_sc01",
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
            "bucket",
            "--show-code",
            "OP",
            "--show-type",
            "vfx",
            "--direct-upload-path",
            "invalid-path",
        ],
    )

    assert result.exit_code != 0


def test_publish_cli_rejects_dangerous_scene_name(tmp_path: Path) -> None:
    renders = tmp_path / "renders"
    renders.mkdir()
    (renders / "beauty.exr").write_text("beauty")

    previews = tmp_path / "previews"
    previews.mkdir()
    (previews / "preview.jpg").write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("otio")

    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"shot": "010"}))

    destination = tmp_path / "package"
    destination.mkdir()

    result = runner.invoke(
        app,
        [
            "--dcc",
            "Nuke",
            "--scene-name",
            "../evil",
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
            "bucket",
            "--show-code",
            "OP",
        ],
    )

    assert result.exit_code != 0
    assert "Invalid value for --scene-name" in result.output
    assert "scene_name must be a simple name" in result.output
