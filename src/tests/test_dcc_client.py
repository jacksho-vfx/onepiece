"""Tests for the DCC client helpers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from libraries.dcc.dcc_client import (
    DCC_ASSET_REQUIREMENTS,
    DCCDependencyReport,
    SupportedDCC,
    _build_launch_command,
    open_scene,
    publish_scene,
    verify_dcc_dependencies,
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
    monkeypatch.setattr("libraries.dcc.dcc_client.os.name", os_name, raising=False)

    scene_path = Path("/tmp/test_scene.mb")
    command = _build_launch_command(SupportedDCC.MAYA, scene_path)

    expected_path = str(scene_path)
    if os_name == "nt":
        expected_path = str(scene_path).replace("/", "\\")

    assert command == [expected, expected_path]


def test_verify_dcc_dependencies_detects_missing(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    report = verify_dcc_dependencies(
        SupportedDCC.NUKE,
        package,
        plugin_inventory=["CaraVR"],
    )

    assert report.plugins.missing == frozenset({"OCIO"})
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


def _create_publish_inputs(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, str], Path]:
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

    metadata: dict[str, str] = {"shot": "010"}

    destination = tmp_path / "published"

    return renders, previews, otio, metadata, destination


@patch("libraries.dcc.dcc_client.s5_sync")
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


@patch("libraries.dcc.dcc_client.s5_sync")
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


@patch("libraries.dcc.dcc_client.s5_sync")
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
    assert "missing plugins: OCIO" in message
    assert "missing assets: missing/asset.txt" in message
    sync_mock.assert_not_called()
