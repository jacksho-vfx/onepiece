from pathlib import Path

from libraries.creative.dcc.lighting_presets import load_lighting_preset


def test_layer_stack_order_respects_sublayers_and_sequence_override() -> None:
    preset_root = Path(__file__).resolve().parents[4] / "assets" / "lighting_presets"
    preset = load_lighting_preset(
        "studio",
        exposure="plus_1",
        sequence_override=Path("overrides/sequence_sh010.usda"),
        root=preset_root,
    )

    assert [path.name for path in preset.layer_stack] == [
        "studio_base.usda",
        "studio_exposure_plus_1.usda",
        "sequence_sh010.usda",
    ]


def test_attribute_overrides_resolve_using_layer_strength() -> None:
    preset_root = Path(__file__).resolve().parents[4] / "assets" / "lighting_presets"
    preset = load_lighting_preset(
        "sunset",
        exposure="plus_1",
        sequence_override=Path("overrides/sequence_sh020.usda"),
        root=preset_root,
    )

    key_light = preset.prim_attributes["Lighting/Key"]
    bounce_light = preset.prim_attributes["Lighting/Bounce"]

    assert key_light["intensity"] == 1120
    assert key_light["color"] == (0.96, 0.84, 0.72)

    assert bounce_light["intensity"] == 400
    assert bounce_light["exposure"] == 0.35
