"""Tests for Maya and Nuke scene save helpers."""

from __future__ import annotations

from pathlib import Path
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


def test_maya_save_scene_with_explicit_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Saving with a path should delegate to ``pm.saveAs``."""

    captured: dict[str, object] = {}

    def fake_save_as(path: str) -> None:
        captured["path"] = path
        captured["parent_exists_at_call"] = Path(path).parent.exists()

    monkeypatch.setattr(maya.pm, "saveAs", fake_save_as, raising=False)

    scene_path = UPath(tmp_path / "maya" / "test_scene.ma")
    parent = scene_path.parent

    assert not parent.exists()

    maya.save_scene(scene_path)

    assert captured["path"] == str(scene_path)
    assert captured["parent_exists_at_call"] is True
    assert parent.exists()


def test_maya_save_scene_defaults_to_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saving without a path should call the internal ``_save`` helper."""

    calls: list[dict[str, object]] = []

    def fake_save(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(maya, "_save", fake_save)

    maya.save_scene()

    assert calls == [{"force": True}]


def test_maya_export_scene_creates_parent_directories(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Exporting a scene should create parent directories before delegating."""

    captured: dict[str, object] = {}

    def fake_export_all(path: UPath, **kwargs: object) -> None:
        captured["path"] = path
        captured["kwargs"] = kwargs
        captured["parent_exists_at_call"] = path.parent.exists()

    monkeypatch.setattr(maya, "_export_all", fake_export_all)

    export_path = UPath(tmp_path / "exports" / "scene.ma")
    parent = export_path.parent

    assert not parent.exists()

    maya.export_scene(export_path)

    assert captured["path"] == export_path
    assert captured["kwargs"] == {"force": True, "type": "mayaAscii"}
    assert captured["parent_exists_at_call"] is True
    assert parent.exists()


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
