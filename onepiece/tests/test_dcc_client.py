import json
from pathlib import Path
from unittest.mock import patch

from onepiece.dcc.dcc_client import SupportedDCC, open_scene, publish_scene


@patch("subprocess.run")
def test_open_nuke_scene(mock_run):
    from pathlib import Path

    file_path = Path("/tmp/test_scene.nk")
    open_scene(SupportedDCC.NUKE, file_path)
    mock_run.assert_called_once_with(["Nuke", str(file_path)], check=True)


@patch("subprocess.run")
def test_open_maya_scene(mock_run):
    file_path = Path("/tmp/test_scene.mb")
    open_scene(SupportedDCC.MAYA, file_path)
    mock_run.assert_called_once_with(["Maya", str(file_path)], check=True)


def test_publish_scene(tmp_path):
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

    metadata = {"shot": "010", "artist": "Luffy"}

    destination = tmp_path / "published"

    with patch("onepiece.dcc.dcc_client.sync_to_bucket") as sync_mock:
        package_path = publish_scene(
            SupportedDCC.NUKE,
            scene_name="ep01_sh010",
            renders=renders,
            previews=previews,
            otio=otio,
            metadata=metadata,
            destination=destination,
            bucket="onepiece-bucket",
            show_code="OP",
            show_type="vfx",
        )

    expected_package = destination / "ep01_sh010"
    assert package_path == expected_package
    assert (expected_package / "renders" / render_file.name).read_text() == "beauty"
    assert (expected_package / "previews" / preview_file.name).read_text() == "preview"
    assert (expected_package / "otio" / otio.name).read_text() == "otio data"

    metadata_path = expected_package / "metadata.json"
    assert json.loads(metadata_path.read_text()) == metadata

    thumbnail = expected_package / "thumbnails" / preview_file.name
    assert thumbnail.exists()

    sync_mock.assert_called_once_with(
        bucket="onepiece-bucket",
        show_code="OP",
        folder="ep01_sh010",
        local_path=expected_package,
        show_type="vfx",
        profile=None,
    )
