from __future__ import annotations

import importlib
import sys
import types

import pytest


@pytest.fixture()
def stub_chopper_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("apps", "apps.chopper", "apps.chopper.renderer"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    apps_module = types.ModuleType("apps")
    apps_module.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "apps", apps_module)

    chopper_pkg = types.ModuleType("apps.chopper")
    chopper_pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "apps.chopper", chopper_pkg)

    renderer_module = types.ModuleType("apps.chopper.renderer")

    class _DummyScene:
        @classmethod
        def from_dict(cls, payload: dict[str, object]) -> dict[str, object]:
            return payload

    renderer_module.Scene = _DummyScene
    renderer_module.SceneError = ValueError
    renderer_module.Renderer = object
    renderer_module.AnimationWriter = object

    monkeypatch.setitem(sys.modules, "apps.chopper.renderer", renderer_module)


def test_load_scene_raises_when_file_cannot_be_decoded(
    tmp_path, stub_chopper_renderer: None
) -> None:
    chopper = importlib.import_module("libraries.automation.render.chopper")
    importlib.reload(chopper)

    scene_path = tmp_path / "scene.json"
    scene_path.write_bytes(b"\xff\xfe\xfa")

    with pytest.raises(chopper.ChopperRenderError) as exc_info:
        chopper.load_scene(scene_path)

    assert "could not be decoded" in str(exc_info.value)
