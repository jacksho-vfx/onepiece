"""Compatibility wrapper to run the package level validation tests."""

from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from apps.onepiece.validate import app as validate_app
from libraries.tests.test_validations import *  # noqa: F401,F403
from libraries.validations import asset_consistency
from libraries.validations.dcc import (
    DCCEnvironmentReport,
    GPUValidation,
    PluginValidation,
    SupportedDCC,
)
from libraries.validations.naming_batch import validate_names_in_csv


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
            required=frozenset({"CaraVR", "OCIO"}),
            available=frozenset({"CaraVR", "OCIO"}),
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
    assert "required: CaraVR, OCIO" in result.stdout
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
