from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

import pytest

from libraries.creative.dcc import HoudiniClient


class FakeNode:
    def __init__(self, path: str) -> None:
        self._path = path

    def path(self) -> str:
        return self._path


class FakeHipFile:
    def __init__(
        self,
        path: str,
        *,
        is_new: bool = False,
        unsaved: bool = False,
        merge_error: Exception | None = None,
    ) -> None:
        self._path = path
        self._is_new = is_new
        self._unsaved = unsaved
        self._merge_error = merge_error
        self.merge_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def path(self) -> str:
        return self._path

    def isNewFile(self) -> bool:
        return self._is_new

    def hasUnsavedChanges(self) -> bool:
        return self._unsaved

    def merge(self, *args: object, **kwargs: object) -> None:
        if self._merge_error:
            raise self._merge_error
        self.merge_calls.append((args, kwargs))


class FakePlaybar:
    def __init__(self, frame_range: tuple[float, float]) -> None:
        self._frame_range = frame_range

    def frameRange(self) -> tuple[float, float]:
        return self._frame_range


class FakeViewport:
    def __init__(
        self, size: tuple[int, int] = (1920, 1080), *, fail: bool = False
    ) -> None:
        self._size = size
        self._fail = fail
        self.saved: list[str] = []

    def saveViewToImage(self, output_path: str) -> None:
        if self._fail:
            raise RuntimeError("save failed")
        self.saved.append(output_path)

    def size(self) -> tuple[int, int]:
        return self._size


class FakeSceneViewer:
    def __init__(self, viewport: FakeViewport | None) -> None:
        self._viewport = viewport

    def curViewport(self) -> FakeViewport | None:
        return self._viewport


class FakeDesktop:
    def __init__(self, viewer: FakeSceneViewer | None) -> None:
        self._viewer = viewer

    def paneTabOfType(self, _pane_type: object) -> FakeSceneViewer | None:
        return self._viewer


class FakeUI:
    def __init__(self, desktop: FakeDesktop) -> None:
        self._desktop = desktop

    def curDesktop(self) -> FakeDesktop:
        return self._desktop


def install_hou(
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: str = "/projects/ep01/ep01_sh010.hip",
    is_new: bool = False,
    unsaved: bool = False,
    selected: Iterable[str] | None = None,
    frame_range: tuple[float, float] = (101.0, 200.0),
    resolution: tuple[int, int] = (1920, 1080),
    viewport: bool = True,
    merge_error: Exception | None = None,
) -> SimpleNamespace:
    hipfile = FakeHipFile(path, is_new=is_new, unsaved=unsaved, merge_error=merge_error)
    nodes = [FakeNode(node) for node in (selected or [])]
    viewport_obj = FakeViewport(size=resolution) if viewport else None
    viewer = FakeSceneViewer(viewport_obj) if viewport_obj else None
    desktop = FakeDesktop(viewer)
    ui = FakeUI(desktop)
    playbar = FakePlaybar(frame_range)

    hou_module = SimpleNamespace(
        hipFile=hipfile,
        playbar=playbar,
        ui=ui,
        paneTabType=SimpleNamespace(SceneViewer="SceneViewer"),
        selectedNodes=lambda: list(nodes),
    )
    monkeypatch.setitem(sys.modules, "hou", hou_module)
    return hou_module


def test_get_current_scene_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    install_hou(monkeypatch, path="/projects/ep01/ep01_sh010.hip")
    client = HoudiniClient()

    assert client.get_current_scene() == "/projects/ep01/ep01_sh010.hip"


def test_get_current_scene_unsaved(monkeypatch: pytest.MonkeyPatch) -> None:
    install_hou(monkeypatch, path="untitled.hip", is_new=True)
    client = HoudiniClient()

    assert client.get_current_scene() is None


def test_get_selected_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    install_hou(monkeypatch, selected=["/obj/geo1", "/obj/geo2"])
    client = HoudiniClient()

    assert client.get_selected_nodes() == ["/obj/geo1", "/obj/geo2"]


def test_apply_template_success(monkeypatch: pytest.MonkeyPatch) -> None:
    hou_module = install_hou(monkeypatch)
    client = HoudiniClient()

    assert client.apply_template("/templates/base.hip") is True
    assert hou_module.hipFile.merge_calls


def test_apply_template_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    install_hou(monkeypatch, merge_error=RuntimeError("bad merge"))
    client = HoudiniClient()

    assert client.apply_template("/templates/base.hip") is False


def test_export_thumbnail_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    hou_module = install_hou(monkeypatch, resolution=(1280, 720))
    output = tmp_path / "thumb.jpg"
    client = HoudiniClient()

    assert client.export_thumbnail(str(output)) is True
    desktop = hou_module.ui.curDesktop()
    viewer = desktop.paneTabOfType(hou_module.paneTabType.SceneViewer)
    viewport = viewer.curViewport() if viewer else None
    assert viewport is not None
    assert viewport.saved == [str(output)]


def test_export_thumbnail_missing_viewport(monkeypatch: pytest.MonkeyPatch) -> None:
    install_hou(monkeypatch, viewport=False)
    client = HoudiniClient()

    assert client.export_thumbnail("/tmp/none.jpg") is False


def test_export_metadata_collects_houdini_details(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_hou(
        monkeypatch,
        path="/projects/ep01/ep01_sh010.hip",
        selected=["/obj/geo1"],
        frame_range=(101.3, 200.6),
        resolution=(2048, 1556),
    )
    client = HoudiniClient()
    output = tmp_path / "metadata.json"

    metadata = client.export_metadata(str(output))

    assert metadata["dcc"] == "houdini"
    assert metadata["scene_path"] == "/projects/ep01/ep01_sh010.hip"
    assert metadata["frame_range"] == [101, 201]
    assert metadata["resolution"] == [2048, 1556]
    assert metadata["selected_nodes"] == ["/obj/geo1"]
    assert json.loads(output.read_text()) == metadata


def test_validate_scene_flags_unsaved(monkeypatch: pytest.MonkeyPatch) -> None:
    install_hou(monkeypatch, path="untitled.hip", is_new=True, unsaved=True)
    client = HoudiniClient()

    issues = client.validate_scene()

    assert "not been saved" in issues[0]


def test_validate_scene_flags_unsaved_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    install_hou(monkeypatch, unsaved=True)
    client = HoudiniClient()

    issues = client.validate_scene()

    assert any("unsaved changes" in issue for issue in issues)
