from pathlib import Path

import pytest

from plugins.variant_switcher import maya
from plugins.variant_switcher.core import StageVariants


USD_STAGE = """#usda 1.0
(
    defaultPrim = "Root"
    variants = {
        string lod = "low"
    }
)

def Xform "Root" {
    variantSet "lod" = {
        "low" { payload = @assets/low.usd@ }
        "high" { payload = @assets/high.usd@ }
    }
}
"""


@pytest.fixture()
def stage_path(tmp_path: Path) -> Path:
    path = tmp_path / "stage.usda"
    path.write_text(USD_STAGE)
    return path


def test_list_variants_reports_payloads(stage_path: Path) -> None:
    variants = maya.list_variants(stage_path)

    assert len(variants) == 1
    lod = variants[0]
    assert lod.name == "lod"
    assert lod.active_selection == "low"
    assert {option.name for option in lod.options} == {"low", "high"}
    assert any("assets/low.usd" in str(option.payloads[0]) for option in lod.options)


def test_switch_variant_updates_selection_and_relinks(
    stage_path: Path, tmp_path: Path
) -> None:
    assets = stage_path.parent / "assets"
    assets.mkdir()
    target_payload = assets / "high.usd"
    target_payload.write_text("high payload")

    activation = maya.switch_variant(
        stage_path,
        "lod",
        "high",
        search_paths=[tmp_path],
    )

    updated = stage_path.read_text()
    assert 'string lod = "high"' in updated
    assert f"@{target_payload.resolve()}@" in updated
    assert activation.relinked_payloads == {
        "assets/high.usd": str(target_payload.resolve())
    }


def test_switch_variant_triggers_viewport_refresh(stage_path: Path) -> None:
    refreshed: list[bool] = []

    def refresh() -> None:
        refreshed.append(True)

    maya.switch_variant(stage_path, "lod", "low", refresh_viewport=refresh)

    assert refreshed == [True]


def test_stage_variants_raises_for_missing_option(stage_path: Path) -> None:
    manager = StageVariants(stage_path)
    with pytest.raises(KeyError):
        manager.activate("lod", "invalid")
