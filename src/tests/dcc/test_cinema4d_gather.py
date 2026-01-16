from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path

cinema4d_gather = import_module("libraries.creative.dcc.cinema4d.gather")


def _write_metadata(package_dir: Path, payload: dict[str, object]) -> None:
    metadata_path = package_dir / "metadata.json"
    metadata_path.write_text(json.dumps(payload))


def test_gather_references_copies_missing_assets(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "tex").mkdir()
    (source_root / "presets").mkdir()

    (source_root / "tex" / "diffuse.png").write_text("texture")
    (source_root / "presets" / "lighting.c4d").write_text("preset")

    _write_metadata(
        package_dir,
        {
            "cinema4d": {
                "textures": ["tex/diffuse.png", "tex/specular.png"],
                "presets": ["presets/lighting.c4d"],
            }
        },
    )

    result = cinema4d_gather.gather_references(package_dir, source_root=source_root)

    copied = set(result.copied)
    assert copied == {"tex/diffuse.png", "presets/lighting.c4d"}
    assert result.missing == ("tex/specular.png",)
    assert result.issues == ()

    assert (package_dir / "tex" / "diffuse.png").exists()
    assert (package_dir / "presets" / "lighting.c4d").exists()
    assert not (package_dir / "tex" / "specular.png").exists()


def test_gather_references_reports_invalid_entries(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()

    _write_metadata(
        package_dir,
        {
            "cinema4d": {
                "textures": ["../escape.jpg", "tex/valid.png"],
                "presets": ["/absolute.preset"],
            }
        },
    )

    result = cinema4d_gather.gather_references(package_dir)

    assert result.copied == ()
    assert result.missing == ("tex/valid.png",)
    assert any("escape" in issue for issue in result.issues)
    assert any("absolute" in issue for issue in result.issues)
