"""Tests for the DCC client helpers."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from libraries.creative.dcc.dcc_client import (
    DCC_ASSET_REQUIREMENTS,
    DCCDependencyReport,
    DCCAssetStatus,
    DCCPluginStatus,
    SupportedDCC,
    _assemble_dependency_report,
    _build_launch_command,
    _prepare_package_contents,
    _sync_package_to_s3,
    _write_metadata_and_thumbnails,
    open_scene,
    publish_scene,
    verify_dcc_dependencies,
)
from libraries.creative.dcc.maya.unreal_export_checker import (
    UnrealExportIssue,
    UnrealExportReport,
)


@patch("subprocess.run")
def test_open_nuke_scene(mock_run: MagicMock) -> None:
    file_path = Path("/tmp/test_scene.nk")

    open_scene(SupportedDCC.NUKE, file_path)

    mock_run.assert_called_once_with(["Nuke", str(file_path)], check=True)


@patch("subprocess.run")
def test_open_maya_scene(mock_run: MagicMock) -> None:
    file_path = Path("/tmp/test_scene.mb")

    open_scene(SupportedDCC.MAYA, file_path)

    mock_run.assert_called_once_with(
        [
            SupportedDCC.MAYA.command,
            str(file_path),
        ],
        check=True,
    )


@pytest.mark.parametrize(
    ("os_name", "expected"),
    (("posix", "maya"), ("nt", "maya.exe")),
)
def test_build_launch_command_maya_binary(
    monkeypatch: pytest.MonkeyPatch, os_name: str, expected: str
) -> None:
    monkeypatch.setattr(
        "libraries.creative.dcc.dcc_client.os", SimpleNamespace(name=os_name)
    )

    scene_path = Path("/tmp/test_scene.mb")
    command = _build_launch_command(SupportedDCC.MAYA, scene_path)

    assert command == [expected, str(scene_path)]


def test_verify_dcc_dependencies_detects_missing(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    report = verify_dcc_dependencies(
        SupportedDCC.NUKE,
        package,
        plugin_inventory=["CaraVR"],
    )

    assert report.plugins.missing == frozenset({"ocio"})
    missing_assets = {path.relative_to(package) for path in report.assets.missing}
    expected_assets = {
        Path(asset) for asset in DCC_ASSET_REQUIREMENTS[SupportedDCC.NUKE]
    }
    assert missing_assets == expected_assets
    assert report.is_valid is False


def test_verify_dcc_dependencies_succeeds(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    for asset in DCC_ASSET_REQUIREMENTS[SupportedDCC.NUKE]:
        target = package / asset
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("payload")

    report = verify_dcc_dependencies(
        SupportedDCC.NUKE,
        package,
        plugin_inventory=["CaraVR", "OCIO"],
    )

    assert report.plugins.missing == frozenset()
    assert report.assets.missing == tuple()
    assert report.is_valid is True


def test_verify_dcc_dependencies_handles_mixed_case_plugin_inventory(
    tmp_path: Path,
) -> None:
    package = tmp_path / "package"
    package.mkdir()

    report = verify_dcc_dependencies(
        SupportedDCC.NUKE,
        package,
        plugin_inventory=["CaraVR", "OCIO", "CustomPlugin"],
        required_plugins=["CustomPlugin"],
    )

    expected = frozenset({"caravr", "ocio", "customplugin"})
    assert report.plugins.available == expected
    assert report.plugins.required == expected
    assert report.plugins.missing == frozenset()


def _create_publish_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, Any], Path]:
    renders = tmp_path / "renders"
    renders.mkdir()
    render_file = renders / "beauty.exr"
    render_file.write_text("beauty")

    previews = tmp_path / "previews"
    previews.mkdir()
    preview_file = previews / "preview.jpg"
    preview_file.write_text("preview")

    otio = tmp_path / "edit.otio"
    otio.write_text("otio data")

    metadata: dict[str, Any] = {"shot": "010"}

    destination = tmp_path / "published"

    return renders, previews, otio, metadata, destination


def test_prepare_package_contents_copies_outputs(tmp_path: Path) -> None:
    renders, previews, otio, _metadata, destination = _create_publish_inputs(tmp_path)

    package_dir, render_files, preview_files = _prepare_package_contents(
        "ep01_sh099", renders, previews, otio, destination
    )

    expected_package = destination / "ep01_sh099"
    assert package_dir == expected_package
    assert render_files == [expected_package / "renders" / "beauty.exr"]
    assert preview_files == [expected_package / "previews" / "preview.jpg"]
    assert (expected_package / "otio" / "edit.otio").exists()


@pytest.mark.parametrize(
    "scene_name",
    ["../evil", "/tmp/hack", "shot/../evil", "shot\\evil", "..", "."],
)
def test_prepare_package_contents_rejects_dangerous_scene_names(
    tmp_path: Path, scene_name: str
) -> None:
    renders, previews, otio, _metadata, destination = _create_publish_inputs(tmp_path)

    with pytest.raises(ValueError) as excinfo:
        _prepare_package_contents(scene_name, renders, previews, otio, destination)

    assert "scene_name must be a simple name" in str(excinfo.value)


def test_write_metadata_and_thumbnails_prefers_previews(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    previews_dir = package_dir / "previews"
    previews_dir.mkdir()
    preview_file = previews_dir / "preview.jpg"
    preview_file.write_text("preview")

    renders_dir = package_dir / "renders"
    renders_dir.mkdir()
    render_file = renders_dir / "beauty.exr"
    render_file.write_text("beauty")

    metadata_path, thumbnail_path = _write_metadata_and_thumbnails(
        package_dir,
        {"shot": "010"},
        [preview_file],
        [render_file],
    )

    assert json.loads(metadata_path.read_text()) == {"shot": "010"}
    expected_thumbnail = package_dir / "thumbnails" / "preview.jpg"
    assert thumbnail_path == expected_thumbnail
    assert expected_thumbnail.exists()


def test_write_metadata_and_thumbnails_falls_back_to_renders(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    render_file = package_dir / "beauty.exr"
    render_file.write_text("beauty")

    metadata_path, thumbnail_path = _write_metadata_and_thumbnails(
        package_dir,
        {"shot": "020"},
        [],
        [render_file],
    )

    assert json.loads(metadata_path.read_text()) == {"shot": "020"}
    expected_thumbnail = package_dir / "thumbnails" / "beauty.exr"
    assert thumbnail_path == expected_thumbnail
    assert expected_thumbnail.exists()


def test_assemble_dependency_report_invokes_callback(
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    report = DCCDependencyReport(
        dcc=SupportedDCC.NUKE,
        plugins=DCCPluginStatus(
            required=frozenset({"CaraVR"}),
            available=frozenset({"CaraVR"}),
            missing=frozenset(),
        ),
        assets=DCCAssetStatus(
            required=(),
            present=(),
            missing=(),
        ),
    )

    callback = MagicMock()

    with patch(
        "libraries.creative.dcc.dcc_client.verify_dcc_dependencies",
        return_value=report,
    ) as verify_mock:
        result = _assemble_dependency_report(
            SupportedDCC.NUKE,
            package_dir,
            dependency_callback=callback,
        )

    assert result is report
    callback.assert_called_once_with(report)
    verify_mock.assert_called_once_with(
        SupportedDCC.NUKE,
        package_dir,
        plugin_inventory=None,
        env=None,
        required_plugins=None,
        required_assets=None,
    )


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_sync_package_to_s3_uses_expected_destination(
    sync_mock: MagicMock, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    with caplog.at_level(logging.INFO):
        destination = _sync_package_to_s3(
            package_dir,
            dcc=SupportedDCC.NUKE,
            scene_name="ep01_sh030",
            bucket="libraries-bucket",
            show_code="OP",
            show_type="vfx",
            dry_run=True,
            profile="artist",
            direct_s3_path=None,
        )

    assert destination == "s3://libraries-bucket/ep01_sh030"
    sync_mock.assert_called_once_with(
        source=package_dir,
        destination=destination,
        dry_run=True,
        include=None,
        exclude=None,
        profile="artist",
    )
    assert "publish_scene_packaged" in caplog.text


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_supports_direct_upload(
    sync_mock: MagicMock, tmp_path: Path
) -> None:
    renders, previews, otio, metadata, destination = _create_publish_inputs(tmp_path)

    callbacks: list[DCCDependencyReport] = []

    def callback(report: DCCDependencyReport) -> None:
        callbacks.append(report)

    package_path = publish_scene(
        SupportedDCC.NUKE,
        scene_name="ep01_sh010",
        renders=renders,
        previews=previews,
        otio=otio,
        metadata=metadata,
        destination=destination,
        bucket="libraries-bucket",
        show_code="OP",
        show_type="vfx",
        profile="artist-profile",
        direct_s3_path="s3://custom/path",
        dependency_callback=callback,
        plugin_inventory=["CaraVR", "OCIO"],
        required_plugins=[],
        required_assets=(),
    )

    expected_package = destination / "ep01_sh010"
    assert package_path == expected_package
    assert callbacks and callbacks[0].is_valid

    sync_mock.assert_called_once_with(
        source=expected_package,
        destination="s3://custom/path",
        dry_run=False,
        include=None,
        exclude=None,
        profile="artist-profile",
    )

    metadata_path = expected_package / "metadata.json"
    assert json.loads(metadata_path.read_text()) == metadata


@patch("libraries.creative.dcc.dcc_client.validate_unreal_export")
@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_runs_maya_validation(
    sync_mock: MagicMock,
    validate_mock: MagicMock,
    tmp_path: Path,
) -> None:
    renders, previews, otio, metadata, destination = _create_publish_inputs(tmp_path)
    metadata["maya"] = {
        "unreal_export": {
            "asset_name": "SK_Hero",
            "scale": 1.0,
            "skeleton_summary": {
                "root": "root",
                "joints": ["root", "pelvis", "spine_01"],
            },
        }
    }

    report = UnrealExportReport(
        asset_name="SK_Hero",
        scale_valid=True,
        skeleton_valid=True,
        naming_valid=True,
        issues=(),
    )
    validate_mock.return_value = report

    callbacks: list[UnrealExportReport] = []

    package_path = publish_scene(
        SupportedDCC.MAYA,
        scene_name="ep01_sh030",
        renders=renders,
        previews=previews,
        otio=otio,
        metadata=metadata,
        destination=destination,
        bucket="libraries-bucket",
        show_code="OP",
        show_type="vfx",
        plugin_inventory=["mtoa", "bifrost"],
        required_assets=(),
        maya_validation_callback=callbacks.append,
    )

    expected_package = destination / "ep01_sh030"
    assert package_path == expected_package

    validate_mock.assert_called_once()
    kwargs = validate_mock.call_args.kwargs
    assert kwargs["asset_name"] == "SK_Hero"
    assert kwargs["scale"] == pytest.approx(1.0)
    assert kwargs["skeleton_root"] == "root"
    assert kwargs["joints"] == ("root", "pelvis", "spine_01")

    assert callbacks == [report]
    sync_mock.assert_called_once()


@patch("libraries.creative.dcc.dcc_client.validate_unreal_export")
@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_maya_validation_failure(
    sync_mock: MagicMock,
    validate_mock: MagicMock,
    tmp_path: Path,
) -> None:
    renders, previews, otio, metadata, destination = _create_publish_inputs(tmp_path)
    metadata["maya"] = {
        "unreal_export": {
            "asset_name": "SK_Villain",
            "scale": 1.0,
            "skeleton_summary": {
                "root": "world",
                "joints": ["world"],
            },
        }
    }

    issue = UnrealExportIssue(
        code="SKELETON_ROOT_MISMATCH",
        message="Skeleton root must be root",
        severity="error",
    )
    report = UnrealExportReport(
        asset_name="SK_Villain",
        scale_valid=True,
        skeleton_valid=False,
        naming_valid=True,
        issues=(issue,),
    )
    validate_mock.return_value = report

    callbacks: list[UnrealExportReport] = []

    with pytest.raises(RuntimeError) as excinfo:
        publish_scene(
            SupportedDCC.MAYA,
            scene_name="ep01_sh031",
            renders=renders,
            previews=previews,
            otio=otio,
            metadata=metadata,
            destination=destination,
            bucket="libraries-bucket",
            show_code="OP",
            show_type="vfx",
            plugin_inventory=["mtoa", "bifrost"],
            required_assets=(),
            maya_validation_callback=callbacks.append,
        )

    assert "SKELETON_ROOT_MISMATCH" in str(excinfo.value)
    assert callbacks == [report]
    sync_mock.assert_not_called()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_honours_dry_run(sync_mock: MagicMock, tmp_path: Path) -> None:
    renders, previews, otio, metadata, destination = _create_publish_inputs(tmp_path)

    package_path = publish_scene(
        SupportedDCC.NUKE,
        scene_name="ep01_sh011",
        renders=renders,
        previews=previews,
        otio=otio,
        metadata=metadata,
        destination=destination,
        bucket="libraries-bucket",
        show_code="OP",
        show_type="vfx",
        dry_run=True,
        plugin_inventory=["CaraVR", "OCIO"],
        required_plugins=[],
        required_assets=(),
    )

    expected_package = destination / "ep01_sh011"
    assert package_path == expected_package
    assert (expected_package / "metadata.json").exists()

    sync_mock.assert_called_once_with(
        source=expected_package,
        destination="s3://libraries-bucket/ep01_sh011",
        dry_run=True,
        include=None,
        exclude=None,
        profile=None,
    )


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_replaces_existing_file_targets(
    sync_mock: MagicMock, tmp_path: Path
) -> None:
    renders, previews, otio, metadata, destination = _create_publish_inputs(tmp_path)

    existing_package = destination / "ep01_sh012"
    existing_package.mkdir(parents=True, exist_ok=True)
    existing_target = existing_package / "previews"
    existing_target.write_text("stale")

    package_path = publish_scene(
        SupportedDCC.NUKE,
        scene_name="ep01_sh012",
        renders=renders,
        previews=previews,
        otio=otio,
        metadata=metadata,
        destination=destination,
        bucket="libraries-bucket",
        show_code="OP",
        show_type="vfx",
        plugin_inventory=["CaraVR", "OCIO"],
        required_plugins=[],
        required_assets=(),
    )

    expected_package = destination / "ep01_sh012"
    assert package_path == expected_package
    previews_dir = expected_package / "previews"
    assert previews_dir.is_dir()
    assert (previews_dir / "preview.jpg").read_text() == "preview"

    sync_mock.assert_called_once()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_dependency_failure_blocks_upload(
    sync_mock: MagicMock, tmp_path: Path
) -> None:
    renders, previews, otio, metadata, destination = _create_publish_inputs(tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        publish_scene(
            SupportedDCC.NUKE,
            scene_name="ep01_sh020",
            renders=renders,
            previews=previews,
            otio=otio,
            metadata=metadata,
            destination=destination,
            bucket="libraries-bucket",
            show_code="OP",
            show_type="vfx",
            plugin_inventory=["CaraVR"],
            required_plugins=["OCIO"],
            required_assets=("renders/beauty.exr", "missing/asset.txt"),
        )

    message = str(excinfo.value)
    assert "missing plugins: ocio" in message
    assert "missing assets: missing/asset.txt" in message
    sync_mock.assert_not_called()
