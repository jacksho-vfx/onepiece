from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from libraries.creative.dcc.cinema4d.validation import validate_package
from libraries.creative.dcc.dcc_client import (
    _assemble_dependency_report,
    _format_dependency_error,
    verify_dcc_dependencies,
)
from libraries.creative.dcc.models import (
    DCC_ASSET_REQUIREMENTS,
    DCCDependencyReport,
    DCCAssetStatus,
    DCCGPUStatus,
    DCCPluginStatus,
    SupportedDCC,
)


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
        env={"ONEPIECE_NUKE_GPU": "OpenGL 4.1"},
    )

    assert report.plugins.missing == frozenset()
    assert report.assets.missing == tuple()
    assert report.gpu == DCCGPUStatus(
        required="OpenGL 4.1",
        detected="OpenGL 4.1",
        meets_requirement=True,
    )
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
        env={"ONEPIECE_NUKE_GPU": "OpenGL 4.1"},
    )

    expected = frozenset({"caravr", "ocio", "customplugin"})
    assert report.plugins.available == expected
    assert report.plugins.required == expected
    assert report.plugins.missing == frozenset()


def test_verify_dcc_dependencies_detects_gpu_failure(tmp_path: Path) -> None:
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
        env={"ONEPIECE_NUKE_GPU": "Integrated Graphics 6000"},
    )

    assert report.gpu == DCCGPUStatus(
        required="OpenGL 4.1",
        detected="Integrated Graphics 6000",
        meets_requirement=False,
    )
    assert report.is_valid is False


def test_verify_dcc_dependencies_cinema4d_missing_assets(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    report = verify_dcc_dependencies(
        SupportedDCC.CINEMA4D,
        package,
        plugin_inventory=["redshift"],
    )

    assert report.plugins.missing == frozenset()
    missing_assets = {path.relative_to(package) for path in report.assets.missing}
    expected_assets = {
        Path(asset) for asset in DCC_ASSET_REQUIREMENTS[SupportedDCC.CINEMA4D]
    }
    assert missing_assets == expected_assets
    assert report.is_valid is False


def test_verify_dcc_dependencies_cinema4d_succeeds(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    for asset in DCC_ASSET_REQUIREMENTS[SupportedDCC.CINEMA4D]:
        target = package / asset
        if target.suffix:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("payload")
        else:
            target.mkdir(parents=True, exist_ok=True)

    report = verify_dcc_dependencies(
        SupportedDCC.CINEMA4D,
        package,
        plugin_inventory=["redshift"],
        env={"ONEPIECE_CINEMA4D_GPU": "Maxon Certified OpenGL 4.5"},
    )

    assert report.plugins.missing == frozenset()
    assert report.assets.missing == tuple()
    assert report.is_valid is True


def _write_cinema4d_metadata(package: Path, payload: dict[str, Any]) -> None:
    metadata_path = package / "metadata.json"
    metadata_path.write_text(json.dumps(payload))


def test_validate_cinema4d_rejects_absolute_reference(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    absolute_path = "/outside/textures/wood.tx"
    _write_cinema4d_metadata(
        package,
        {"cinema4d": {"textures": [absolute_path]}},
    )

    issues = validate_package(package)

    assert issues == [
        f"Cinema4D references must be relative to the package: {absolute_path}"
    ]


def test_validate_cinema4d_rejects_windows_absolute_reference(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    windows_path = r"C:\\assets\\textures\\hero.tx"
    _write_cinema4d_metadata(
        package,
        {"cinema4d": {"textures": [windows_path]}},
    )

    issues = validate_package(package)

    assert len(issues) == 1
    assert "Cinema4D references must be relative to the package" in issues[0]
    assert windows_path in issues[0]


def test_validate_cinema4d_rejects_traversal_reference(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    traversal_path = "../presets/outside.c4d"
    _write_cinema4d_metadata(
        package,
        {"cinema4d": {"presets": [traversal_path]}},
    )

    issues = validate_package(package)

    assert issues == [
        f"Cinema4D references must stay within the package: {traversal_path}"
    ]


def test_validate_cinema4d_accepts_relative_references(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    texture_path = package / "tex" / "mat.tx"
    texture_path.parent.mkdir(parents=True, exist_ok=True)
    texture_path.write_text("payload")

    preset_path = package / "presets" / "lighting.c4d"
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    preset_path.write_text("payload")

    _write_cinema4d_metadata(
        package,
        {
            "cinema4d": {
                "textures": ["tex/mat.tx"],
                "presets": ["presets/lighting.c4d"],
            }
        },
    )

    issues = validate_package(package)

    assert issues == []


def test_format_dependency_error_includes_gpu_details(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()

    report = DCCDependencyReport(
        dcc=SupportedDCC.NUKE,
        plugins=DCCPluginStatus(
            required=frozenset(),
            available=frozenset(),
            missing=frozenset(),
        ),
        assets=DCCAssetStatus(required=(), present=(), missing=()),
        gpu=DCCGPUStatus(
            required="OpenGL 4.1",
            detected="Integrated Graphics 6000",
            meets_requirement=False,
        ),
    )

    message = _format_dependency_error(report, package)

    assert "GPU requirement not met" in message
    assert "Integrated Graphics 6000" in message


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
        gpu_description=None,
        required_gpu=None,
    )
