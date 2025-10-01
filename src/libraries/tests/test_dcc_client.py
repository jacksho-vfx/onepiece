from pathlib import Path
from unittest.mock import patch, MagicMock

import json
import pytest

from libraries.dcc.dcc_client import (
    DCC_ASSET_REQUIREMENTS,
    DCCDependencyReport,
    SupportedDCC,
    open_scene,
    publish_scene,
    verify_dcc_dependencies,
)


@patch("subprocess.run")
def test_open_nuke_scene(mock_run: MagicMock) -> None:
    from pathlib import Path

    file_path = Path("/tmp/test_scene.nk")
    open_scene(SupportedDCC.NUKE, file_path)
    mock_run.assert_called_once_with(["Nuke", str(file_path)], check=True)


@patch("subprocess.run")
def test_open_maya_scene(mock_run: MagicMock) -> None:
    file_path = Path("/tmp/test_scene.mb")
    open_scene(SupportedDCC.MAYA, file_path)
    mock_run.assert_called_once_with(["Maya", str(file_path)], check=True)


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


def _create_publish_inputs(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, str], Path]:
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
    )

    metadata_path = expected_package / "metadata.json"
    assert json.loads(metadata_path.read_text()) == metadata


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


# def test_publish_scene(tmp_path: Path) -> None:
#     renders = tmp_path / "renders"
#     renders.mkdir()
#     render_file = renders / "beauty.exr"
#     render_file.write_text("beauty")
#
#     previews = tmp_path / "previews"
#     previews.mkdir()
#     preview_file = previews / "preview.jpg"
#     preview_file.write_text("preview")
#
#     otio = tmp_path / "edit.otio"
#     otio.write_text("otio data")
#
#     metadata: dict[str, JSONValue] = {"shot": "010", "artist": "Luffy"}
#
#     destination = tmp_path / "published"
#
#     with patch("libraries.dcc.dcc_client.s5_sync") as sync_mock:
#         sync_mock.assert_called_once_with(
#             source=expected_package,
#             target_bucket="libraries-bucket",
#             context="ep01_sh010",
#             dry_run=False,
#             include=None,
#             exclude=None,
#         )
#
#     expected_package = destination / "ep01_sh010"
#     assert package_path == expected_package
#     assert (expected_package / "renders" / render_file.name).read_text() == "beauty"
#     assert (expected_package / "previews" / preview_file.name).read_text() == "preview"
#     assert (expected_package / "otio" / otio.name).read_text() == "otio data"
#
#     metadata_path = expected_package / "metadata.json"
#     assert json.loads(metadata_path.read_text()) == metadata
#
#     thumbnail = expected_package / "thumbnails" / preview_file.name
#     assert thumbnail.exists()
#
#     sync_mock.assert_called_once_with(
#         bucket="libraries-bucket",
#         show_code="OP",
#         folder="ep01_sh010",
#         local_path=expected_package,
#         show_type="vfx",
#         profile=None,
#     )
