from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from libraries.creative.dcc.dcc_client import _build_launch_command, open_scene
from libraries.creative.dcc.models import SupportedDCC


@patch("subprocess.run")
def test_open_nuke_scene(mock_run: MagicMock) -> None:
    file_path = Path("/tmp/test_scene.nk")

    open_scene(SupportedDCC.NUKE, file_path)

    mock_run.assert_called_once_with(["Nuke", str(file_path)], check=True)


@patch("subprocess.run")
def test_open_maya_scene(mock_run: MagicMock) -> None:
    file_path = Path("/tmp/test_scene.mb")

    open_scene(SupportedDCC.MAYA, file_path)

    mock_run.assert_called_once_with(
        [
            SupportedDCC.MAYA.command,
            str(file_path),
        ],
        check=True,
    )


@pytest.mark.parametrize(
    ("os_name", "expected"),
    (("posix", "maya"), ("nt", "maya.exe")),
)
def test_build_launch_command_maya_binary(
    monkeypatch: pytest.MonkeyPatch, os_name: str, expected: str
) -> None:
    monkeypatch.setattr(
        "libraries.creative.dcc.dcc_client.os", SimpleNamespace(name=os_name)
    )

    scene_path = Path("/tmp/test_scene.mb")
    command = _build_launch_command(SupportedDCC.MAYA, scene_path)

    assert command == [expected, str(scene_path)]
