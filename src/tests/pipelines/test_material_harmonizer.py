from pathlib import Path

import pytest

from libraries.creative.dcc.material_harmonizer import (
    MaterialHarmonizer,
    UsdShadeParseError,
)


SAMPLE_USD = """#usda 1.0
(
    defaultPrim = "HeroMaterial"
)

def Material "HeroMaterial" {
    token outputs:surface.connect = </HeroMaterial/PreviewSurface.outputs:surface>
    def Shader "PreviewSurface" {
        string info:id = "UsdPreviewSurface"
        color3f inputs:diffuseColor.connect = </HeroMaterial/DiffuseTex.outputs:rgb>
    }
    def Shader "DiffuseTex" {
        string info:id = "UsdUVTexture"
        asset inputs:file = @textures/hero_diffuse.exr@
        string inputs:sourceColorSpace = "ACEScg"
    }
    def Shader "NormalTex" {
        string info:id = "UsdUVTexture"
        asset inputs:file = @textures/hero_normal.exr@
        string inputs:sourceColorSpace = "raw"
    }
}
"""


@pytest.fixture()
def harmonizer() -> MaterialHarmonizer:
    return MaterialHarmonizer()


def test_parse_usdshade_extracts_textures_and_colorspace(
    harmonizer: MaterialHarmonizer,
) -> None:
    network = harmonizer.parse_usdshade(SAMPLE_USD)

    assert network.material_name == "HeroMaterial"
    assert network.surface_shader == "UsdPreviewSurface"
    assert len(network.textures) == 2
    assert {texture.colorspace for texture in network.textures} == {"ACEScg", "raw"}


def test_translate_relinks_textures_and_preserves_colorspace(
    tmp_path: Path, harmonizer: MaterialHarmonizer
) -> None:
    diffuse = tmp_path / "hero_diffuse.exr"
    normal = tmp_path / "hero_normal.exr"
    diffuse.write_text("diffuse")
    normal.write_text("normal")

    translations = harmonizer.translate(
        SAMPLE_USD,
        texture_search_paths=[tmp_path],
    )

    assert len(translations) == 3
    cinema_translation = translations[0]

    diffuse_node = next(
        node for node in cinema_translation.nodes if "diffuse" in node["name"]
    )
    assert Path(diffuse_node["file"]) == diffuse
    assert diffuse_node[cinema_translation.template.colorspace_attribute] == "ACEScg"


def test_round_trip_returns_relinked_snapshot(
    tmp_path: Path, harmonizer: MaterialHarmonizer
) -> None:
    texture_dir = tmp_path / "textures"
    texture_dir.mkdir()
    (texture_dir / "hero_diffuse.exr").write_text("diffuse")
    (texture_dir / "hero_normal.exr").write_text("normal")

    translations = harmonizer.translate(
        SAMPLE_USD,
        texture_search_paths=[texture_dir],
        targets=["cinema4d"],
    )
    translation = translations[0]

    usd_snapshot = translation.to_usd_template()

    assert usd_snapshot["material"] == "HeroMaterial"
    assert usd_snapshot["surface"] == "C4DStandardSurface"
    assert {entry["colorspace"] for entry in usd_snapshot["textures"]} == {
        "ACEScg",
        "raw",
    }
    assert all(
        Path(entry["file"]).is_absolute() or "textures" in entry["file"]
        for entry in usd_snapshot["textures"]
    )


def test_parse_fails_without_material() -> None:
    malformed = 'def Shader "OnlyShader" {}'
    with pytest.raises(UsdShadeParseError):
        MaterialHarmonizer().parse_usdshade(malformed)
