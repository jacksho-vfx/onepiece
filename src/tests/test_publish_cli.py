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

runner = CliRunner()


class Called(TypedDict, total=False):
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


def _dependency_report() -> DCCDependencyReport:
    return DCCDependencyReport(
        dcc=SupportedDCC.NUKE,
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
            "--direct-upload-path",
            "s3://bucket/custom/path",
            "--dependency-summary",
        ],
    )

    assert result.exit_code == 0, result.output
    assert called["args"][0] is SupportedDCC.NUKE
    assert called["kwargs"]["direct_s3_path"] == "s3://bucket/custom/path"
    assert "Dependency summary for Nuke" in result.output
    assert "Plugins missing: None" in result.output


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
