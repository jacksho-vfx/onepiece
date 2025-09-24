import pytest
from unittest.mock import patch
from onepiece.dcc.dcc_client import SupportedDCC, open_scene

@patch("subprocess.run")
def test_open_nuke_scene(mock_run):
    from pathlib import Path
    file_path = Path("/tmp/test_scene.nk")
    open_scene(SupportedDCC.NUKE, file_path)
    mock_run.assert_called_once_with(["Nuke", str(file_path)], check=True)

@patch("subprocess.run")
def test_open_maya_scene(mock_run):
    from pathlib import Path
    file_path = Path("/tmp/test_scene.mb")
    open_scene(SupportedDCC.MAYA, file_path)
    mock_run.assert_called_once_with(["Maya", str(file_path)], check=True)
