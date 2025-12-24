from pathlib import Path

from tools.turntable_gen import generate_turntable_stage


def _extract_rotation_samples(stage_content: str) -> dict[int, float]:
    samples: dict[int, float] = {}
    for line in stage_content.splitlines():
        stripped = line.strip()
        if ":" in stripped and stripped[0].isdigit():
            frame_text, value_text = stripped.split(":", 1)
            samples[int(frame_text.strip())] = float(value_text.strip())
    return samples


def test_turntable_stage_layers_assets_and_presets(tmp_path: Path) -> None:
    asset_layer = tmp_path / "asset.usda"
    asset_layer.write_text("#usda 1.0\n", encoding="utf-8")

    package = generate_turntable_stage(asset_layer, tmp_path / "out")
    stage_text = package.stage_path.read_text(encoding="utf-8")

    assert "asset.usda" in stage_text
    assert "studio_base.usda" in stage_text
    assert "RenderCamera" in stage_text
    assert f"startTimeCode = {package.frame_range[0]}" in stage_text
    assert f"endTimeCode = {package.frame_range[1]}" in stage_text


def test_turntable_animation_spans_full_rotation(tmp_path: Path) -> None:
    asset_layer = tmp_path / "hero.usda"
    asset_layer.write_text("#usda 1.0\n", encoding="utf-8")

    frame_range = (1001, 1120)
    package = generate_turntable_stage(
        asset_layer, tmp_path / "output", frame_range=frame_range
    )
    stage_text = package.stage_path.read_text(encoding="utf-8")

    samples = _extract_rotation_samples(stage_text)
    assert samples[frame_range[0]] == 0.0
    assert samples[frame_range[1]] == 360.0


def test_templates_reference_generated_stage(tmp_path: Path) -> None:
    asset_layer = tmp_path / "sample.usda"
    asset_layer.write_text("#usda 1.0\n", encoding="utf-8")

    package = generate_turntable_stage(asset_layer, tmp_path / "showcase")

    stage_path = package.stage_path.as_posix()
    unreal = package.templates.unreal_level_sequence

    assert unreal["stage"] == stage_path
    assert unreal["frame_range"]["start"] == package.frame_range[0]
    assert unreal["frame_range"]["end"] == package.frame_range[1]

    assert stage_path in package.templates.nuke_read
    assert stage_path in package.templates.nuke_write
