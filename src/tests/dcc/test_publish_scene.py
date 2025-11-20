from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from apps.onepiece.dcc.publish import app as publish_app
from libraries.creative.dcc.dcc_client import (
    _prepare_package_contents,
    _sync_package_to_s3,
    _write_metadata_and_thumbnails,
    publish_scene,
)
from libraries.creative.dcc.models import (
    DCCDependencyReport,
    DCCAssetStatus,
    DCCGPUStatus,
    DCCPluginStatus,
    SupportedDCC,
)
from libraries.creative.dcc.maya.unreal_export_checker import (
    UnrealExportIssue,
    UnrealExportReport,
)

PublishInputs = tuple[Path, Path, Path, dict[str, Any], Path]


def test_prepare_package_contents_copies_outputs(publish_inputs: PublishInputs) -> None:
    renders, previews, otio, _metadata, destination = publish_inputs

    package_dir, render_files, preview_files, _manifest = _prepare_package_contents(
        "ep01_sh099", renders, previews, otio, destination
    )

    expected_package = destination / "ep01_sh099"
    assert package_dir == expected_package
    assert render_files == [expected_package / "renders" / "beauty.exr"]
    assert preview_files == [expected_package / "previews" / "preview.jpg"]
    assert (expected_package / "otio" / "edit.otio").exists()


def test_prepare_package_contents_hardlinks_outputs(
    publish_inputs: PublishInputs,
) -> None:
    renders, previews, otio, _metadata, destination = publish_inputs

    package_dir, render_files, preview_files, _manifest = _prepare_package_contents(
        "ep01_sh099",
        renders,
        previews,
        otio,
        destination,
        link_strategy="hard",
    )

    render_target = render_files[0]
    preview_target = preview_files[0]
    otio_target = package_dir / "otio" / "edit.otio"

    assert os.stat(render_target).st_nlink >= 2
    assert os.stat(render_target).st_ino == os.stat(renders / "beauty.exr").st_ino
    assert os.stat(preview_target).st_nlink >= 2
    assert os.stat(preview_target).st_ino == os.stat(previews / "preview.jpg").st_ino
    assert os.stat(otio_target).st_nlink >= 2
    assert os.stat(otio_target).st_ino == os.stat(otio).st_ino


def test_prepare_package_contents_symlinks_outputs(
    publish_inputs: PublishInputs,
) -> None:
    renders, previews, otio, _metadata, destination = publish_inputs

    package_dir, render_files, preview_files, _manifest = _prepare_package_contents(
        "ep01_sh099",
        renders,
        previews,
        otio,
        destination,
        link_strategy="symlink",
    )

    assert (package_dir / "renders").is_symlink()
    assert (package_dir / "previews").is_symlink()
    assert os.path.samefile(render_files[0], renders / "beauty.exr")
    assert os.path.samefile(preview_files[0], previews / "preview.jpg")
    assert (package_dir / "otio" / "edit.otio").is_symlink()


def test_prepare_package_contents_downgrades_linking_on_failure(
    publish_inputs: PublishInputs,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    renders, previews, otio, _metadata, destination = publish_inputs

    def failing_link(src: str, dst: str) -> None:
        raise OSError("link not supported")

    monkeypatch.setattr(os, "link", failing_link)
    caplog.set_level(logging.WARNING)

    package_dir, render_files, preview_files, _manifest = _prepare_package_contents(
        "ep01_sh099",
        renders,
        previews,
        otio,
        destination,
        link_strategy="hard",
    )

    render_target = render_files[0]
    preview_target = preview_files[0]

    assert os.stat(render_target).st_nlink == 1
    assert os.stat(preview_target).st_nlink == 1
    assert "publish_scene_link_downgraded" in caplog.text


def test_prepare_package_contents_parallel_copy_creates_expected_files(
    publish_inputs: PublishInputs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONEPIECE_DCC_COPY_WORKERS", "2")

    renders, previews, otio, _metadata, destination = publish_inputs

    extra_render = renders / "deep" / "shadow.exr"
    extra_render.parent.mkdir(parents=True, exist_ok=True)
    extra_render.write_text("shadow")

    extra_preview = previews / "plates" / "layout.jpg"
    extra_preview.parent.mkdir(parents=True, exist_ok=True)
    extra_preview.write_text("layout")

    package_dir, render_files, preview_files, manifest = _prepare_package_contents(
        "ep01_sh099", renders, previews, otio, destination
    )

    expected_render_files = [
        package_dir / "renders" / "beauty.exr",
        package_dir / "renders" / "deep" / "shadow.exr",
    ]
    expected_preview_files = [
        package_dir / "previews" / "plates" / "layout.jpg",
        package_dir / "previews" / "preview.jpg",
    ]

    assert render_files == expected_render_files
    assert preview_files == expected_preview_files
    for path in render_files + preview_files:
        assert path.exists() and path.is_file()

    manifest_keys = set(manifest)
    expected_keys = {
        str(path.relative_to(package_dir))
        for path in render_files + preview_files + [package_dir / "otio" / "edit.otio"]
    }
    assert expected_keys <= manifest_keys


def test_prepare_package_contents_parallel_copy_downgrades_once(
    publish_inputs: PublishInputs,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ONEPIECE_DCC_COPY_WORKERS", "4")

    renders, previews, otio, _metadata, destination = publish_inputs
    (renders / "plate.exr").write_text("plate")
    (previews / "alt_preview.jpg").write_text("preview alt")

    def failing_link(src: str, dst: str) -> None:
        raise OSError("link not supported")

    monkeypatch.setattr(os, "link", failing_link)
    caplog.set_level(logging.WARNING)

    package_dir, render_files, preview_files, _manifest = _prepare_package_contents(
        "ep01_sh099",
        renders,
        previews,
        otio,
        destination,
        link_strategy="hard",
    )

    assert all(path.exists() and not path.is_symlink() for path in render_files)
    assert all(path.exists() and not path.is_symlink() for path in preview_files)

    downgrade_records = [
        record
        for record in caplog.records
        if record.message == "publish_scene_link_downgraded"
    ]
    assert len(downgrade_records) == 3

    def _targets_for(segment: str) -> set[str]:
        return {
            getattr(record, "target")
            for record in downgrade_records
            if segment in Path(getattr(record, "target")).parts
        }

    assert len(_targets_for("renders")) == 1
    assert len(_targets_for("previews")) == 1
    assert len(_targets_for("otio")) == 1


def test_metadata_and_thumbnails_are_real_files_when_linking(
    publish_inputs: PublishInputs,
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    package_dir, render_files, preview_files, _manifest = _prepare_package_contents(
        "ep01_sh099",
        renders,
        previews,
        otio,
        destination,
        link_strategy="symlink",
    )

    metadata_path, thumbnail_path = _write_metadata_and_thumbnails(
        package_dir,
        metadata,
        preview_files,
        render_files,
    )

    assert metadata_path.exists() and not metadata_path.is_symlink()
    if thumbnail_path is not None:
        assert thumbnail_path.exists() and not thumbnail_path.is_symlink()


@pytest.mark.parametrize(
    "scene_name",
    ["../evil", "/tmp/hack", "shot/../evil", "shot\\evil", "..", "."],
)
def test_prepare_package_contents_rejects_dangerous_scene_names(
    publish_inputs: PublishInputs, scene_name: str
) -> None:
    renders, previews, otio, _metadata, destination = publish_inputs

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


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_sync_package_to_s3_uses_expected_destination(
    sync_mock: MagicMock, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    with caplog.at_level(logging.INFO):
        destination_path = _sync_package_to_s3(
            package_dir,
            dcc=SupportedDCC.NUKE,
            scene_name="ep01_sh030",
            bucket="libraries-bucket",
            show_code="OP",
            show_type="vfx",
            dry_run=True,
            profile="artist",
            direct_s3_path=None,
            concurrency=None,
            part_size=None,
        )

    expected_destination = "s3://libraries-bucket/vfx/OP/ep01_sh030"
    assert destination_path == expected_destination
    sync_mock.assert_called_once_with(
        source=package_dir,
        destination=expected_destination,
        dry_run=True,
        include=None,
        exclude=None,
        profile="artist",
        concurrency=None,
        part_size=None,
    )
    assert "publish_scene_packaged" in caplog.text


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_supports_direct_upload(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    callbacks: list[DCCDependencyReport] = []

    def callback(report: DCCDependencyReport) -> None:
        callbacks.append(report)

    result = publish_scene(
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
        gpu_description="OpenGL 4.1",
    )

    expected_package = destination / "ep01_sh010"
    assert result.package_dir == expected_package
    assert result.destination == "s3://custom/path"
    assert callbacks and callbacks[0].is_valid

    sync_mock.assert_called_once_with(
        source=expected_package,
        destination="s3://custom/path",
        dry_run=False,
        include=None,
        exclude=None,
        profile="artist-profile",
        concurrency=None,
        part_size=None,
    )

    metadata_path = expected_package / "metadata.json"
    assert json.loads(metadata_path.read_text()) == metadata


@patch("libraries.creative.dcc.packaging._profile_s5cmd_overrides")
@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_forwards_s5cmd_overrides(
    sync_mock: MagicMock,
    profile_override: MagicMock,
    publish_inputs: PublishInputs,
) -> None:
    profile_override.return_value = (None, None)

    renders, previews, otio, metadata, destination = publish_inputs

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
        s5_concurrency=12,
        s5_part_size="32MB",
        plugin_inventory=["CaraVR", "OCIO"],
        required_plugins=[],
        required_assets=(),
        gpu_description="OpenGL 4.1",
    )

    sync_mock.assert_called_once()
    kwargs = sync_mock.call_args.kwargs
    assert kwargs["concurrency"] == 12
    assert kwargs["part_size"] == "32MB"


@patch("libraries.creative.dcc.packaging._profile_s5cmd_overrides")
@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_uses_profile_s5cmd_overrides(
    sync_mock: MagicMock,
    profile_override: MagicMock,
    publish_inputs: PublishInputs,
) -> None:
    profile_override.return_value = (6, "64MB")

    renders, previews, otio, metadata, destination = publish_inputs

    publish_scene(
        SupportedDCC.NUKE,
        scene_name="ep01_sh021",
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
        gpu_description="OpenGL 4.1",
    )

    sync_mock.assert_called_once()
    kwargs = sync_mock.call_args.kwargs
    assert kwargs["concurrency"] == 6
    assert kwargs["part_size"] == "64MB"


@patch("libraries.creative.dcc.dcc_client.validate_unreal_export")
@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_runs_maya_validation(
    sync_mock: MagicMock,
    validate_mock: MagicMock,
    publish_inputs: PublishInputs,
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs
    metadata = metadata.copy()
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

    result = publish_scene(
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
        gpu_description="DirectX 11",
        maya_validation_callback=callbacks.append,
    )

    expected_package = destination / "ep01_sh030"
    assert result.package_dir == expected_package
    assert result.destination == "s3://libraries-bucket/vfx/OP/ep01_sh030"

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
    publish_inputs: PublishInputs,
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs
    metadata = metadata.copy()
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
            gpu_description="DirectX 11",
            maya_validation_callback=callbacks.append,
        )

    assert "SKELETON_ROOT_MISMATCH" in str(excinfo.value)
    assert callbacks == [report]
    sync_mock.assert_not_called()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_cinema4d_validation_failure(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs
    metadata = metadata.copy()
    metadata["cinema4d"] = {
        "textures": ["renders/textures/diffuse.tx"],
        "presets": ["renders/presets/hero.rsp"],
    }

    with pytest.raises(RuntimeError) as excinfo:
        publish_scene(
            SupportedDCC.CINEMA4D,
            scene_name="ep01_sh040",
            renders=renders,
            previews=previews,
            otio=otio,
            metadata=metadata,
            destination=destination,
            bucket="libraries-bucket",
            show_code="OP",
            show_type="vfx",
            plugin_inventory=["redshift"],
            required_assets=(),
            gpu_description="OpenGL 4.5",
        )

    message = str(excinfo.value)
    assert "Cinema4D validation failed" in message
    assert "renders/textures/diffuse.tx" in message
    sync_mock.assert_not_called()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_cinema4d_validation_success(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs
    metadata = metadata.copy()

    texture_file = renders / "textures" / "diffuse.tx"
    texture_file.parent.mkdir(parents=True, exist_ok=True)
    texture_file.write_text("texture data")
    preset_file = renders / "presets" / "hero.rsp"
    preset_file.parent.mkdir(parents=True, exist_ok=True)
    preset_file.write_text("preset data")
    metadata["cinema4d"] = {
        "textures": [{"path": f"renders/textures/{texture_file.name}"}],
        "presets": [f"renders/presets/{preset_file.name}"],
    }

    result = publish_scene(
        SupportedDCC.CINEMA4D,
        scene_name="ep01_sh041",
        renders=renders,
        previews=previews,
        otio=otio,
        metadata=metadata,
        destination=destination,
        bucket="libraries-bucket",
        show_code="OP",
        show_type="vfx",
        plugin_inventory=["redshift"],
        required_assets=(),
        gpu_description="OpenGL 4.5",
    )

    expected_package = destination / "ep01_sh041"
    assert result.package_dir == expected_package
    assert result.destination == "s3://libraries-bucket/vfx/OP/ep01_sh041"
    sync_mock.assert_called_once()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_houdini_validation_success(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    scene_name = "ep01_sh041"
    package_dir = destination / scene_name
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "scene.hiplc").write_text("hip data")
    caches_dir = package_dir / "caches"
    caches_dir.mkdir(parents=True, exist_ok=True)
    (caches_dir / "sim.bgeo").write_text("cache")
    descriptor_dir = package_dir / "packages"
    descriptor_dir.mkdir(parents=True, exist_ok=True)
    (descriptor_dir / "onepiece.json").write_text("{}")

    result = publish_scene(
        SupportedDCC.HOUDINI,
        scene_name=scene_name,
        renders=renders,
        previews=previews,
        otio=otio,
        metadata=metadata,
        destination=destination,
        bucket="libraries-bucket",
        show_code="OP",
        show_type="vfx",
        plugin_inventory=["karma"],
        required_assets=(),
        gpu_description="Vulkan",
    )

    expected_package = destination / scene_name
    assert result.package_dir == expected_package
    assert result.destination == "s3://libraries-bucket/vfx/OP/ep01_sh041"
    assert (expected_package / "caches" / "sim.bgeo").exists()
    assert (expected_package / "packages" / "onepiece.json").exists()
    sync_mock.assert_called_once()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_houdini_validation_failure(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    with pytest.raises(RuntimeError) as excinfo:
        publish_scene(
            SupportedDCC.HOUDINI,
            scene_name="ep01_sh042",
            renders=renders,
            previews=previews,
            otio=otio,
            metadata=metadata,
            destination=destination,
            bucket="libraries-bucket",
            show_code="OP",
            show_type="vfx",
            plugin_inventory=["karma"],
            required_assets=(),
            gpu_description="Vulkan",
        )

    message = str(excinfo.value)
    assert "Houdini validation failed" in message
    assert "scene file" in message
    sync_mock.assert_not_called()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_honours_dry_run(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    result = publish_scene(
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
        gpu_description="OpenGL 4.1",
    )

    expected_package = destination / "ep01_sh011"
    assert result.package_dir == expected_package
    assert result.destination == "s3://libraries-bucket/vfx/OP/ep01_sh011"
    assert (expected_package / "metadata.json").exists()

    sync_mock.assert_called_once_with(
        source=expected_package,
        destination="s3://libraries-bucket/vfx/OP/ep01_sh011",
        dry_run=True,
        include=None,
        exclude=None,
        profile=None,
        concurrency=None,
        part_size=None,
    )


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_replaces_existing_file_targets(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    existing_package = destination / "ep01_sh012"
    existing_package.mkdir(parents=True, exist_ok=True)
    existing_target = existing_package / "previews"
    existing_target.write_text("stale")

    result = publish_scene(
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
        gpu_description="OpenGL 4.1",
    )

    expected_package = destination / "ep01_sh012"
    assert result.package_dir == expected_package
    assert result.destination == "s3://libraries-bucket/vfx/OP/ep01_sh012"
    previews_dir = expected_package / "previews"
    assert previews_dir.is_dir()
    assert (previews_dir / "preview.jpg").read_text() == "preview"

    sync_mock.assert_called_once()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_skips_unchanged_files(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    scene_name = "ep01_sh050"
    publish_scene(
        SupportedDCC.NUKE,
        scene_name=scene_name,
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
        gpu_description="OpenGL 4.1",
    )

    package_dir = destination / scene_name
    render_target = package_dir / "renders" / "beauty.exr"
    preview_target = package_dir / "previews" / "preview.jpg"
    manifest_path = package_dir / ".onepiece-package.json"

    initial_render_inode = os.stat(render_target).st_ino
    initial_preview_inode = os.stat(preview_target).st_ino
    assert manifest_path.exists()

    sync_mock.reset_mock()

    publish_scene(
        SupportedDCC.NUKE,
        scene_name=scene_name,
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
        gpu_description="OpenGL 4.1",
    )

    assert sync_mock.call_count == 1
    assert os.stat(render_target).st_ino == initial_render_inode
    assert os.stat(preview_target).st_ino == initial_preview_inode
    assert manifest_path.exists()


@patch("libraries.creative.dcc.dcc_client.verify_dcc_dependencies")
@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_force_package_rebuilds_outputs(
    sync_mock: MagicMock,
    verify_mock: MagicMock,
    publish_inputs: PublishInputs,
    tmp_path: Path,
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs
    scene_name = "ep01_sh051"

    verify_mock.return_value = DCCDependencyReport(
        dcc=SupportedDCC.NUKE,
        plugins=DCCPluginStatus(
            required=frozenset(), available=frozenset(), missing=frozenset()
        ),
        assets=DCCAssetStatus(required=(), present=(), missing=()),
        gpu=DCCGPUStatus(
            required="OpenGL 4.1", detected="OpenGL 4.1", meets_requirement=True
        ),
    )

    publish_scene(
        SupportedDCC.NUKE,
        scene_name=scene_name,
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
        gpu_description="OpenGL 4.1",
    )

    package_dir = destination / scene_name
    render_target = package_dir / "renders" / "beauty.exr"
    assert render_target.read_text() == "beauty"

    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))

    (renders / "beauty.exr").write_text("Beauty")

    runner = CliRunner()
    result = runner.invoke(
        publish_app,
        [
            "--dcc",
            "nuke",
            "--scene-name",
            scene_name,
            "--renders",
            str(renders),
            "--previews",
            str(previews),
            "--otio",
            str(otio),
            "--metadata",
            str(metadata_path),
            "--destination",
            str(destination),
            "--bucket",
            "libraries-bucket",
            "--show-code",
            "OP",
            "--force-package",
        ],
    )

    assert result.exit_code == 0
    assert render_target.read_text() == "Beauty"


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_dependency_failure_blocks_upload(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

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
            gpu_description="OpenGL 4.1",
        )

    message = str(excinfo.value)
    assert "missing plugins: ocio" in message
    assert "missing assets: missing/asset.txt" in message
    sync_mock.assert_not_called()


@patch("libraries.creative.dcc.dcc_client.s5_sync")
def test_publish_scene_gpu_failure_blocks_upload(
    sync_mock: MagicMock, publish_inputs: PublishInputs
) -> None:
    renders, previews, otio, metadata, destination = publish_inputs

    with pytest.raises(RuntimeError) as excinfo:
        publish_scene(
            SupportedDCC.NUKE,
            scene_name="ep01_sh021",
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
            gpu_description="Legacy GPU without OpenGL",
        )

    message = str(excinfo.value)
    assert "GPU requirement not met" in message
    assert "Legacy GPU" in message
    sync_mock.assert_not_called()
