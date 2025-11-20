"""Tests for the validation helpers and CLI interfaces."""

import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from pytest import MonkeyPatch

from typer.testing import CliRunner

from apps.onepiece.validate import app as validate_app
from libraries.creative.dcc.dcc_client import SupportedDCC
from libraries.platform.validations import dcc as dcc_validations
from libraries.platform.validations import filesystem, naming
from libraries.platform.validations import asset_consistency
from libraries.platform.validations.dcc import (
    DCCEnvironmentReport,
    GPUValidation,
    PluginValidation,
)
from libraries.platform.validations.naming_batch import validate_names_in_csv


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


def test_check_paths_expands_environment_variables(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    dir_path = tmp_path / "env"
    dir_path.mkdir()
    monkeypatch.setenv("ONEPIECE_RENDER_DIR", str(dir_path))

    results = filesystem.check_paths(["$ONEPIECE_RENDER_DIR"])

    resolved_dir = str(dir_path.resolve())
    assert resolved_dir in results
    assert results[resolved_dir]["exists"] is True
    assert results[resolved_dir]["writable"] is True


def test_check_paths_expands_user_directory(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    home_dir = tmp_path / "home"
    renders_dir = home_dir / "renders"
    renders_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home_dir))

    results = filesystem.check_paths(["~/renders"])

    resolved_dir = str(renders_dir.resolve())
    assert resolved_dir in results
    assert results[resolved_dir]["exists"] is True
    assert results[resolved_dir]["writable"] is True


# ---------- DCC detection ----------


def test_validate_dcc_supports_vray() -> None:
    assert dcc_validations.validate_dcc("vray") is SupportedDCC.VRAY


def test_validate_dcc_supports_cinema4d() -> None:
    assert dcc_validations.validate_dcc("cinema4d") is SupportedDCC.CINEMA4D


def test_validate_dcc_accepts_aliases() -> None:
    assert dcc_validations.validate_dcc("max") is SupportedDCC.MAX
    assert dcc_validations.validate_dcc("c4d") is SupportedDCC.CINEMA4D


def test_detect_dcc_from_file_supports_vray() -> None:
    assert (
        dcc_validations.detect_dcc_from_file("/projects/shot/lighting.vrscene")
        is SupportedDCC.VRAY
    )


def test_detect_dcc_from_file_supports_cinema4d() -> None:
    assert (
        dcc_validations.detect_dcc_from_file("/projects/shot/lookdev.c4d")
        is SupportedDCC.CINEMA4D
    )


@pytest.mark.parametrize("extension", [".hip", ".hiplc", ".hipnc"])
def test_detect_dcc_from_file_supports_houdini(extension: str) -> None:
    assert (
        dcc_validations.detect_dcc_from_file(f"/projects/shot/lighting{extension}")
        is SupportedDCC.HOUDINI
    )


@patch("libraries.platform.validations.dcc.shutil.which", return_value=None)
def test_detect_executable_respects_empty_path(mock_which: MagicMock) -> None:
    installed, executable = dcc_validations._detect_executable(
        SupportedDCC.NUKE, {"PATH": ""}
    )

    mock_which.assert_called_once_with(
        SupportedDCC.NUKE.resolve_command({"PATH": ""}), path=""
    )
    assert installed is False
    assert executable is None


@patch("libraries.platform.validations.dcc.shutil.which", return_value=None)
def test_detect_executable_without_path_env(mock_which: MagicMock) -> None:
    installed, executable = dcc_validations._detect_executable(SupportedDCC.MAYA, {})

    mock_which.assert_called_once_with(SupportedDCC.MAYA.resolve_command({}), path="")
    assert installed is False
    assert executable is None


def test_detect_houdini_uses_hfs_bin(tmp_path: Path) -> None:
    hfs_root = tmp_path / "hfs"
    bin_dir = hfs_root / "bin"
    bin_dir.mkdir(parents=True)

    houdini_exec = bin_dir / "houdini"
    houdini_exec.write_text("")
    houdini_exec.chmod(houdini_exec.stat().st_mode | 0o111)

    env = {"HFS": str(hfs_root), "PATH": ""}

    installed, executable = dcc_validations._detect_executable(
        SupportedDCC.HOUDINI, env
    )

    assert installed is True
    assert executable == str(houdini_exec)


def test_detect_houdini_falls_back_to_aliases(tmp_path: Path) -> None:
    fx_dir = tmp_path / "fx"
    fx_dir.mkdir()
    fx_executable = fx_dir / "houdinifx"
    fx_executable.write_text("")
    fx_executable.chmod(fx_executable.stat().st_mode | 0o111)

    hython_dir = tmp_path / "hython"
    hython_dir.mkdir()
    hython_executable = hython_dir / "hython"
    hython_executable.write_text("")
    hython_executable.chmod(hython_executable.stat().st_mode | 0o111)

    env = {
        "PATH": f"{fx_dir}{os.pathsep}{hython_dir}",
    }

    installed, executable = dcc_validations._detect_executable(
        SupportedDCC.HOUDINI, env
    )

    assert installed is True
    assert executable == str(fx_executable)


def test_check_paths_handles_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "renders"

    results = filesystem.check_paths([target])

    resolved_target = str(target.resolve())
    info = results[resolved_target]

    assert info["exists"] is False
    assert info["writable"] is True
    assert info["free_space_gb"] > 0


# ---------- Naming ----------


def test_validate_show_name() -> None:
    assert naming.validate_show_name("blob01")
    assert naming.validate_show_name("frog99")
    assert naming.validate_show_name("frog")
    assert naming.validate_show_name("XYZ")
    assert not naming.validate_show_name("01frog")


def test_validate_episode_scene_shot_names() -> None:
    assert naming.validate_episode_name("ep101")
    assert naming.validate_scene_name("sc01")
    assert naming.validate_shot("0010")
    assert naming.validate_shot_name("ep101_sc01_0010")
    assert naming.validate_asset_name("ep101_sc01_0010_asset")
    assert not naming.validate_asset_name("ep101_sc01_0010-asset")


@patch(
    "libraries.platform.validations.dcc.shutil.which",
    return_value="/opt/Nuke14/Nuke14.0",
)
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


@patch(
    "libraries.platform.validations.dcc.shutil.which",
    return_value="/opt/Nuke14/Nuke14.0",
)
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


@patch("libraries.platform.validations.dcc.shutil.which", return_value=None)
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


@patch("libraries.platform.validations.dcc.shutil.which", return_value="/usr/bin/vray")
def test_check_dcc_environment_vray_gpu_requirement(mock_which: MagicMock) -> None:
    report = dcc_validations.check_dcc_environment(
        SupportedDCC.VRAY,
        env={},
        plugin_inventory={SupportedDCC.VRAY: frozenset({"vray"})},
        gpu_info={SupportedDCC.VRAY: "NVIDIA RTX / CUDA 11"},
    )

    assert report.installed is True
    assert report.plugins.missing == frozenset()
    assert report.gpu.required == "CUDA 11"
    assert report.gpu.meets_requirement is True


@patch(
    "libraries.platform.validations.dcc.shutil.which",
    return_value="/Applications/Maxon Cinema 4D/Cinema 4D",
)
def test_check_dcc_environment_reports_missing_cinema4d_dependencies(
    mock_which: MagicMock,
) -> None:
    report = dcc_validations.check_dcc_environment(
        SupportedDCC.CINEMA4D,
        env={},
    )

    assert report.installed is True
    assert report.plugins.missing == frozenset({"redshift"})
    assert report.gpu.meets_requirement is False


@patch(
    "libraries.platform.validations.dcc.shutil.which",
    return_value="/Applications/Maxon Cinema 4D/Cinema 4D",
)
def test_check_dcc_environment_cinema4d_succeeds(
    mock_which: MagicMock,
) -> None:
    plugin_inventory = {SupportedDCC.CINEMA4D: frozenset({"redshift"})}
    gpu_info = {SupportedDCC.CINEMA4D: "NVIDIA RTX / OpenGL 4.5"}

    report = dcc_validations.check_dcc_environment(
        SupportedDCC.CINEMA4D,
        env={},
        plugin_inventory=plugin_inventory,
        gpu_info=gpu_info,
    )

    assert report.plugins.missing == frozenset()
    assert report.gpu.meets_requirement is True


@patch(
    "libraries.platform.validations.dcc.shutil.which",
    return_value="/opt/Houdini/bin/houdini",
)
def test_check_dcc_environment_reports_missing_karma(
    mock_which: MagicMock, tmp_path: Path
) -> None:
    houdini_root = tmp_path / "houdini"
    packages_dir = houdini_root / "packages"
    packages_dir.mkdir(parents=True)
    (packages_dir / "onepiece.json").write_text("{}")

    env = {
        "PATH": str(houdini_root),
        "HOUDINI_PATH": str(houdini_root),
    }

    report = dcc_validations.check_dcc_environment(
        SupportedDCC.HOUDINI,
        env=env,
    )

    assert "karma" in report.plugins.missing
    assert "packages/onepiece.json" not in report.plugins.missing


@patch(
    "libraries.platform.validations.dcc.shutil.which",
    return_value="/opt/Houdini/bin/houdini",
)
def test_check_dcc_environment_reports_invalid_houdini_path(
    mock_which: MagicMock,
) -> None:
    env = {
        "PATH": "/opt/Houdini/bin",
        "HOUDINI_PATH": "/not/a/real/path",
    }

    report = dcc_validations.check_dcc_environment(
        SupportedDCC.HOUDINI,
        env=env,
        plugin_inventory={SupportedDCC.HOUDINI: frozenset({"karma"})},
    )

    assert "packages/onepiece.json" in report.plugins.missing
    assert "karma" not in report.plugins.missing


@patch(
    "libraries.platform.validations.dcc.shutil.which",
    return_value="/opt/Houdini/bin/houdini",
)
def test_check_dcc_environment_uses_hconfig_paths(
    mock_which: MagicMock, tmp_path: Path
) -> None:
    package_root = tmp_path / "houdini"
    package_dir = package_root / "packages"
    package_dir.mkdir(parents=True)
    (package_dir / "onepiece.json").write_text("{}")

    env = {
        "PATH": "/opt/Houdini/bin",
        "HOUDINI_HCONFIG": f"HOUDINI_PATH = {package_root}{os.pathsep}&",
    }

    report = dcc_validations.check_dcc_environment(
        SupportedDCC.HOUDINI,
        env=env,
    )

    assert report.plugins.missing == frozenset({"karma"})


# ---------- CLI extensions ----------


@patch("libraries.platform.validations.asset_consistency.scan_s3_context")
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


@patch("libraries.platform.validations.asset_consistency.scan_s3_context")
def test_s3_parity_normalises_numeric_versions(mock_scan: MagicMock) -> None:
    manifest: Dict[str, List[Any]] = {"sh010": [1, "002", "v3"]}
    mock_scan.return_value = [
        {"shot": "SH010", "version": "v001"},
        {"shot": "sh010", "version": "V002"},
        {"shot": "sh010", "version": "v003"},
    ]

    report = asset_consistency.check_shot_versions_s3(manifest, "Demo", "vendor_in")

    assert report.missing == {}
    assert report.unexpected == {}
    assert report.is_clean is True


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


@patch("apps.onepiece.validate.dcc_environment.check_dcc_environment")
def test_dcc_environment_cli_accepts_aliases(mock_check: MagicMock) -> None:
    mock_check.return_value = DCCEnvironmentReport(
        dcc=SupportedDCC.MAX,
        installed=True,
        executable="C:/Program Files/Autodesk/3ds Max 2024/3dsmax.exe",
        plugins=PluginValidation(
            required=frozenset({"vray"}),
            available=frozenset({"vray"}),
            missing=frozenset(),
        ),
        gpu=GPUValidation(
            required="DirectX 12", detected="NVIDIA RTX", meets_requirement=True
        ),
    )

    runner = CliRunner()
    result = runner.invoke(validate_app, ["dcc-environment", "--dcc", "max"])

    assert result.exit_code == 0
    mock_check.assert_called_once_with(SupportedDCC.MAX)
