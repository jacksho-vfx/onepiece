"""Tests for the shared DCC client scaffolding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from libraries.creative.dcc import (
    BaseDCCClient,
    BlenderClient,
    DCC,
    HoudiniClient,
    Cinema4DClient,
    MaxClient,
    MayaClient,
    NukeClient,
    VrayClient,
)


CLIENT_CLASSES = {
    DCC.MAYA: MayaClient,
    DCC.NUKE: NukeClient,
    DCC.HOUDINI: HoudiniClient,
    DCC.BLENDER: BlenderClient,
    DCC.MAX: MaxClient,
    DCC.VRAY: VrayClient,
    DCC.CINEMA4D: Cinema4DClient,
}


@pytest.mark.parametrize("dcc, client_cls", CLIENT_CLASSES.items())
def test_get_current_scene_not_implemented(
    dcc: DCC, client_cls: type[BaseDCCClient]
) -> None:
    client = client_cls()
    with pytest.raises(NotImplementedError):
        client.get_current_scene()


@pytest.mark.parametrize("dcc, client_cls", CLIENT_CLASSES.items())
def test_get_selected_nodes_returns_empty_list(
    dcc: DCC, client_cls: type[BaseDCCClient]
) -> None:
    client = client_cls()
    assert client.get_selected_nodes() == []


@pytest.mark.parametrize("dcc, client_cls", CLIENT_CLASSES.items())
def test_apply_template_returns_false(
    dcc: DCC, client_cls: type[BaseDCCClient]
) -> None:
    client = client_cls()
    assert client.apply_template("/path/to/template") is False


@pytest.mark.parametrize("dcc, client_cls", CLIENT_CLASSES.items())
def test_export_thumbnail_returns_false(
    dcc: DCC, client_cls: type[BaseDCCClient]
) -> None:
    client = client_cls()
    assert client.export_thumbnail("/tmp/output.jpg") is False


@pytest.mark.parametrize("dcc, client_cls", CLIENT_CLASSES.items())
def test_export_metadata_creates_json(
    tmp_path: Path, dcc: DCC, client_cls: type[BaseDCCClient]
) -> None:
    client = client_cls()
    output = tmp_path / f"{dcc.name.lower()}_metadata.json"
    metadata = client.export_metadata(str(output))

    assert output.exists()
    file_metadata = json.loads(output.read_text())
    assert metadata == file_metadata
    assert set(metadata).issuperset(
        {"scene_path", "scene_file", "identifier", "user", "date"}
    )


def test_export_metadata_includes_scene_path(tmp_path: Path) -> None:
    class FakeClient(BaseDCCClient):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__(dcc=DCC.MAYA)

        def get_current_scene(self) -> str | None:
            return "/projects/ep01/ep01_sh010.ma"

    client = FakeClient()
    output = tmp_path / "metadata.json"

    metadata = client.export_metadata(str(output))

    assert metadata["scene_path"] == "/projects/ep01/ep01_sh010.ma"
    assert metadata["scene_file"] == "ep01_sh010.ma"


@pytest.mark.parametrize("dcc, client_cls", CLIENT_CLASSES.items())
def test_check_plugins_returns_false_map(
    dcc: DCC, client_cls: type[BaseDCCClient]
) -> None:
    client = client_cls()
    plugins = client.check_plugins(["plugin_a", "plugin_b"])
    assert plugins == {"plugin_a": False, "plugin_b": False}


@pytest.mark.parametrize("dcc, client_cls", CLIENT_CLASSES.items())
def test_validate_scene_returns_placeholder(
    dcc: DCC, client_cls: type[BaseDCCClient]
) -> None:
    client = client_cls()
    issues = client.validate_scene()
    assert issues == [f"{dcc.value} validation not implemented"]


def test_cinema4d_export_metadata_merges_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary: dict[str, Any] = {
        "frame_range": [101.2, 200.6],
        "renderer": "  Redshift  ",
        "take": " Beauty ",
        "additional": {"passes": 3},
        "resolution": [3840, 2160],
    }
    summary_path = tmp_path / "c4d_summary.json"
    summary_path.write_text(json.dumps(summary))
    monkeypatch.setenv("ONEPIECE_CINEMA4D_SUMMARY", str(summary_path))

    client = Cinema4DClient()
    output = tmp_path / "metadata.json"
    metadata = client.export_metadata(str(output))

    assert metadata["dcc"] == "cinema4d"
    assert metadata["frame_range"] == [101, 201]
    assert metadata["resolution"] == [3840, 2160]
    assert metadata["cinema4d"]["frame_range"] == [101, 201]
    assert metadata["cinema4d"]["renderer"] == "Redshift"
    assert metadata["cinema4d"]["take"] == "Beauty"
    assert metadata["cinema4d"]["additional"] == {"passes": 3}
    assert metadata["cinema4d"]["resolution"] == [3840, 2160]

    written = json.loads(output.read_text())
    assert written == metadata


def test_cinema4d_export_metadata_without_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONEPIECE_CINEMA4D_SUMMARY", raising=False)

    client = Cinema4DClient()
    output = tmp_path / "metadata.json"
    metadata = client.export_metadata(str(output))

    assert metadata["dcc"] == "cinema4d"
    assert "cinema4d" not in metadata
    assert metadata["frame_range"] is None
    assert metadata["resolution"] is None
