"""Tests for the validation helpers and CLI interfaces."""

from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from apps.onepiece.validate import app as validate_app
from libraries.dcc.dcc_client import SupportedDCC
from libraries.validations import dcc as dcc_validations
from libraries.validations import filesystem, naming
from libraries.validations import asset_consistency
from libraries.validations.dcc import (
    DCCEnvironmentReport,
    GPUValidation,
    PluginValidation,
)
from libraries.validations.naming_batch import validate_names_in_csv


# ---------- Filesystem ----------


def test_check_paths(tmp_path: Path) -> None:
    dir_path = tmp_path / "renders"
    dir_path.mkdir()
    results = filesystem.check_paths([dir_path])
    assert results[str(dir_path)]["exists"]
    assert results[str(dir_path)]["writable"] is True


def test_preflight_report(tmp_path: Path) -> None:
    dir_path = tmp_path / "renders"
    dir_path.mkdir()
    assert filesystem.preflight_report([dir_path]) is True


# ---------- Naming ----------


def test_validate_show_name() -> None:
    assert naming.validate_show_name("blob01")
    assert naming.validate_show_name("frog99")
    assert not naming.validate_show_name("01frog")
    assert not naming.validate_show_name("frog")


def test_validate_episode_scene_shot_names() -> None:
    assert naming.validate_episode_name("ep101")
    assert naming.validate_scene_name("sc01")
    assert naming.validate_shot("0010")
    assert naming.validate_shot_name("ep101_sc01_0010")
    assert naming.validate_asset_name("ep101_sc01_0010_asset")
    assert not naming.validate_asset_name("ep101_sc01_0010-asset")


@patch("libraries.validations.dcc.shutil.which", return_value="/opt/Nuke14/Nuke14.0")
def test_check_dcc_environment_reports_missing_plugins(mock_which: MagicMock) -> None:
    env = {
        "PATH": "/opt/Nuke14",
        "ONEPIECE_NUKE_PLUGINS": "CaraVR",
        "ONEPIECE_NUKE_GPU": "NVIDIA RTX (OpenGL 4.1)",
    }

    report = dcc_validations.check_dcc_environment(SupportedDCC.NUKE, env=env)

    assert report.installed is True
    assert report.executable == "/opt/Nuke14/Nuke14.0"
    assert report.plugins.missing == frozenset({"ocio"})
    assert report.gpu.meets_requirement is True


@patch("libraries.validations.dcc.shutil.which", return_value="/opt/Nuke14/Nuke14.0")
def test_check_dcc_environment_normalises_plugin_inventory(
    mock_which: MagicMock,
) -> None:
    env = {
        "PATH": "/opt/Nuke14",
        "ONEPIECE_NUKE_PLUGINS": "CaraVR, ocio",
    }

    report = dcc_validations.check_dcc_environment(SupportedDCC.NUKE, env=env)

    assert report.plugins.available == frozenset({"caravr", "ocio"})
    assert report.plugins.missing == frozenset()


@patch("libraries.validations.dcc.shutil.which", return_value=None)
def test_check_dcc_environment_missing_gpu(mock_which: MagicMock) -> None:
    report = dcc_validations.check_dcc_environment(
        SupportedDCC.MAYA,
        env={},
        plugin_inventory={SupportedDCC.MAYA: frozenset({"mtoa", "bifrost"})},
        gpu_info={SupportedDCC.MAYA: None},
    )

    assert report.installed is False
    assert report.plugins.missing == frozenset()
    assert report.gpu.meets_requirement is False


# ---------- CLI extensions ----------


@patch("libraries.validations.asset_consistency.scan_s3_context")
def test_s3_parity_reports_missing_and_unexpected(mock_scan: MagicMock) -> None:
    manifest: Dict[str, List[str]] = {"sh001": ["v001", "v002"]}
    mock_scan.return_value = [
        {"shot": "sh001", "version": "v001"},
        {"shot": "sh002", "version": "v003"},
    ]

    report = asset_consistency.check_shot_versions_s3(manifest, "Demo", "vendor_in")

    assert report.missing == {"sh001": ["v002"]}
    assert report.unexpected == {"sh002": ["v003"]}
    assert report.is_clean is False


def test_naming_batch_supports_sequence_patterns(tmp_path: Path) -> None:
    csv_path = tmp_path / "names.csv"
    csv_path.write_text(
        "name\nseq010_sh010\nseq010_sh010_lighting_v002\ninvalid name\n",
        encoding="utf-8",
    )

    results = validate_names_in_csv(csv_path)
    lookup = {result.name: result for result in results}

    assert lookup["seq010_sh010"].valid
    assert "sequence" in lookup["seq010_sh010"].detail
    assert lookup["seq010_sh010_lighting_v002"].valid
    assert "sequence" in lookup["seq010_sh010_lighting_v002"].detail
    assert lookup["invalid name"].valid is False


@patch("apps.onepiece.validate.dcc_environment.check_dcc_environment")
def test_dcc_environment_cli_renders_summary(mock_check: MagicMock) -> None:
    mock_check.return_value = DCCEnvironmentReport(
        dcc=SupportedDCC.NUKE,
        installed=True,
        executable="/opt/Nuke14/Nuke14.0",
        plugins=PluginValidation(
            required=frozenset({"caravr", "ocio"}),
            available=frozenset({"caravr", "ocio"}),
            missing=frozenset(),
        ),
        gpu=GPUValidation(
            required="OpenGL 4.1",
            detected="NVIDIA RTX (OpenGL 4.1)",
            meets_requirement=True,
        ),
    )

    runner = CliRunner()
    result = runner.invoke(validate_app, ["dcc-environment", "--dcc", "Nuke"])

    assert result.exit_code == 0
    assert "Nuke" in result.stdout
    assert "Plugins" in result.stdout
    assert "required: caravr, ocio" in result.stdout
    assert "GPU" in result.stdout
    assert "required: OpenGL 4.1" in result.stdout


@patch("apps.onepiece.validate.dcc_environment.check_dcc_environment")
def test_dcc_environment_cli_flags_failures(mock_check: MagicMock) -> None:
    mock_check.return_value = DCCEnvironmentReport(
        dcc=SupportedDCC.MAYA,
        installed=False,
        executable=None,
        plugins=PluginValidation(
            required=frozenset({"mtoa"}),
            available=frozenset(),
            missing=frozenset({"mtoa"}),
        ),
        gpu=GPUValidation(
            required="DirectX 11", detected=None, meets_requirement=False
        ),
    )

    runner = CliRunner()
    result = runner.invoke(validate_app, ["dcc-environment", "--dcc", "Maya"])

    assert result.exit_code != 0
    assert "require attention" in result.stdout
