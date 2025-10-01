"""Tests for the shared DCC client scaffolding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from libraries.dcc import (
    BaseDCCClient,
    BlenderClient,
    DCC,
    HoudiniClient,
    MaxClient,
    MayaClient,
    NukeClient,
)


CLIENT_CLASSES = {
    DCC.MAYA: MayaClient,
    DCC.NUKE: NukeClient,
    DCC.HOUDINI: HoudiniClient,
    DCC.BLENDER: BlenderClient,
    DCC.MAX: MaxClient,
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
