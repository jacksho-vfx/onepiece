from pathlib import Path

import pytest

from apps.onepiece.render.presets import RenderPreset, RenderPresetStore
from apps.onepiece.utils.errors import OnePieceValidationError


@pytest.fixture()
def stub_capabilities() -> dict[str, int | bool]:
    return {
        "default_priority": 50,
        "priority_min": 10,
        "priority_max": 90,
        "chunk_size_enabled": True,
        "chunk_size_min": 1,
        "chunk_size_max": 10,
    }


def test_render_preset_rejects_capability_drift(
    stub_capabilities: dict[str, int | bool]
) -> None:
    with pytest.raises(OnePieceValidationError) as excinfo:
        RenderPreset.from_mapping(
            "too_low",
            {
                "farm": "mock",
                "dcc": "maya",
                "scene": "/tmp/scene.mb",
                "frames": "1-5",
                "output": "/tmp/output",
                "priority": 1,
            },
            capability_provider=lambda _: stub_capabilities,
        )

    message = str(excinfo.value)
    assert "incompatible" in message
    assert "priority" in message


def test_store_prefers_project_render_presets_directory(
    stub_capabilities: dict[str, int | bool],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    project_root = tmp_path / "project"
    presets_root = project_root / ".onepiece" / "render_presets"
    presets_root.mkdir(parents=True)

    store = RenderPresetStore(
        capability_provider=lambda _: stub_capabilities,
        project_root=project_root,
    )

    preset = RenderPreset.from_mapping(
        "project",
        {
            "farm": "mock",
            "dcc": "maya",
            "scene": str(project_root / "scene.mb"),
            "frames": "1-2",
            "output": str(project_root / "output"),
            "priority": 20,
            "chunk_size": 2,
        },
        capability_provider=store.capability_provider,
    )

    saved_path = store.save(preset)
    assert saved_path.parent == presets_root
    assert saved_path.name == "project.json"
    assert store.roots[0] == presets_root
