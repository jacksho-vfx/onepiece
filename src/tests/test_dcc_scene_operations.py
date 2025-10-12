"""Tests for Maya and Nuke scene save helpers."""

from __future__ import annotations

import sys
import types

import pytest

from upath import UPath

# --------------------------------------------------------------------------- #
# Provide lightweight stubs for DCC modules when unavailable
# --------------------------------------------------------------------------- #
if "nuke" not in sys.modules:
    nuke_stub = types.ModuleType("nuke")
    nuke_stub.scriptOpen = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    nuke_stub.scriptSave = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    nuke_stub.scriptSaveAs = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    nuke_stub.nodePaste = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    sys.modules["nuke"] = nuke_stub

from libraries.dcc.maya import maya
from libraries.dcc.nuke import nuke as nuke_module


def test_maya_save_scene_with_explicit_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving with a path should delegate to ``pm.saveAs``."""

    captured: dict[str, str] = {}

    def fake_save_as(path: str) -> None:
        captured["path"] = path

    monkeypatch.setattr(maya.pm, "saveAs", fake_save_as, raising=False)

    scene_path = UPath("/project/test_scene.ma")
    maya.save_scene(scene_path)

    assert captured["path"] == str(scene_path)


def test_maya_save_scene_defaults_to_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving without a path should call the internal ``_save`` helper."""

    calls: list[dict[str, object]] = []

    def fake_save(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(maya, "_save", fake_save)

    maya.save_scene()

    assert calls == [{"force": True}]


def test_nuke_save_scene_with_explicit_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving with a path should delegate to ``nuke.scriptSaveAs``."""

    captured: dict[str, str] = {}

    def fake_save_as(path: str) -> None:
        captured["path"] = path

    monkeypatch.setattr(nuke_module.nuke, "scriptSaveAs", fake_save_as)

    script_path = UPath("/project/test_script.nk")
    nuke_module.save_scene(script_path)

    assert captured["path"] == str(script_path)


def test_nuke_save_scene_defaults_to_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving without a path should call ``nuke.scriptSave``."""

    called: list[object] = []

    def fake_save() -> None:
        called.append(True)

    monkeypatch.setattr(nuke_module.nuke, "scriptSave", fake_save)

    nuke_module.save_scene()

    assert called == [True]
