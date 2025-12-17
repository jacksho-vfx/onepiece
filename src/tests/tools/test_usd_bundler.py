from pathlib import Path

from tools.usd_bundler import bundle_usd


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_bundle_resolves_dependencies(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "shot.usda",
        """#usda 1.0
(
    subLayers = [@env/lighting.usda@]
)

def Scope "Root" {
    def Shader "DiffuseTex" {
        asset inputs:file = @textures/hero_diffuse.exr@
    }
}
""",
    )
    sublayer = _write(
        tmp_path / "env" / "lighting.usda",
        """#usda 1.0
(
)

def Shader "Env" {
    asset inputs:file = @../tex/env_map.hdr@
}
""",
    )
    texture_a = _write(tmp_path / "textures" / "hero_diffuse.exr", "diffuse")
    texture_b = _write(tmp_path / "tex" / "env_map.hdr", "hdr")

    bundle_dir = tmp_path / "bundle"
    manifest = bundle_usd(root, bundle_dir)

    bundled_root = bundle_dir / manifest.root_layer
    bundled_sublayer = bundle_dir / "layers" / sublayer.name

    assert bundled_root.exists()
    assert bundled_sublayer.exists()

    root_content = bundled_root.read_text(encoding="utf-8")
    sublayer_content = bundled_sublayer.read_text(encoding="utf-8")

    assert "lighting.usda" in root_content
    assert "../textures/hero_diffuse.exr" in root_content
    assert "../textures/env_map.hdr" in sublayer_content

    bundled_textures = {
        artifact.source for artifact in manifest.artifacts if artifact.kind == "texture"
    }
    assert bundled_textures == {texture_a.resolve(), texture_b.resolve()}
    assert manifest.version_hash


def test_bundle_prunes_variants_and_unused_textures(tmp_path: Path) -> None:
    root = _write(
        tmp_path / "asset.usda",
        """#usda 1.0
variants = {
    string lod = "high"
}

variantSet "lod" = {
    "low" {
        def Shader "Texture" {
            asset inputs:file = @textures/low_diffuse.exr@
        }
    }
    "high" {
        def Shader "Texture" {
            asset inputs:file = @textures/high_diffuse.exr@
        }
    }
}
""",
    )

    low_texture = _write(tmp_path / "textures" / "low_diffuse.exr", "low")
    _write(tmp_path / "textures" / "high_diffuse.exr", "high")

    bundle_dir = tmp_path / "bundle"
    manifest = bundle_usd(root, bundle_dir, variants={"lod": "low"})

    bundled_root = bundle_dir / manifest.root_layer
    content = bundled_root.read_text(encoding="utf-8")

    assert "high_diffuse" not in content
    assert "low_diffuse" in content

    bundled_files = {artifact.source.name for artifact in manifest.artifacts}
    assert "high_diffuse.exr" not in bundled_files
    assert low_texture.name in bundled_files
