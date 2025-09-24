import pytest
from unittest.mock import MagicMock
from onepiece.shotgrid.client import ShotgridClient

@pytest.fixture
def sg_client():
    return ShotgridClient()

def test_get_or_create_project_creates_new(sg_client):
    sg_client._find_project = MagicMock(return_value=None)
    sg_client._create_project = MagicMock(return_value={"id": 123, "name": "TestShow"})

    project = sg_client.get_or_create_project("TestShow")
    sg_client._create_project.assert_called_once_with("TestShow")
    assert project["name"] == "TestShow"

def test_get_or_create_project_returns_existing(sg_client):
    sg_client._find_project = MagicMock(return_value={"id": 456, "name": "ExistingShow"})
    sg_client._create_project = MagicMock()

    project = sg_client.get_or_create_project("ExistingShow")
    sg_client._create_project.assert_not_called()
    assert project["id"] == 456


def test_register_version_records_entry(tmp_path):
    client = ShotgridClient()
    file_path = tmp_path / "SHOW01_ep001_sc01_0001_comp.mov"
    file_path.write_text("content")

    version = client.register_version(
        project_name="CoolShow",
        shot_code="ep001_sc01_0001",
        file_path=file_path,
        description="comp",
    )

    assert version["id"] == 1
    assert version["code"] == file_path.stem
    assert client.list_versions()[0]["shot"] == "ep001_sc01_0001"
