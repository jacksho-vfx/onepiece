from pathlib import Path

from libraries.creative.dcc.houdini.validation import validate_package


def test_validate_houdini_package_success(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    hip_file = package_dir / "scene.hip"
    hip_file.write_text("hip data")

    renders_dir = package_dir / "renders"
    renders_dir.mkdir()
    (renders_dir / "beauty.exr").write_text("beauty")

    caches_dir = package_dir / "caches"
    caches_dir.mkdir()
    (caches_dir / "sim.vdb").write_text("cache")

    descriptor_dir = package_dir / "packages"
    descriptor_dir.mkdir()
    (descriptor_dir / "onepiece.json").write_text("{}")

    (package_dir / "metadata.json").write_text("{}")

    assert validate_package(package_dir) == ()


def test_validate_houdini_package_collects_missing_assets(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    issues = validate_package(package_dir)

    assert "scene file" in " ".join(issues)
    assert any("renders" in issue for issue in issues)
    assert any("caches" in issue for issue in issues)
    assert any("descriptor" in issue for issue in issues)
    assert any("metadata" in issue for issue in issues)
    assert len(issues) >= 4
