import pytest
from unittest.mock import MagicMock
from src.libraries.shotgrid.client import ShotgridClient


@pytest.fixture
def sg_client() -> ShotgridClient:
    return ShotgridClient()


def test_get_or_create_project_creates_new(sg_client: ShotgridClient) -> None:
    sg_client._find_project = MagicMock(return_value=None)  # type: ignore[method-assign]
    sg_client._create_project = MagicMock(return_value={"id": 123, "name": "TestShow"})  # type: ignore[method-assign]

    project = sg_client.get_or_create_project("TestShow")
    sg_client._create_project.assert_called_once_with("TestShow")
    assert project["name"] == "TestShow"


def test_get_or_create_project_returns_existing(sg_client: ShotgridClient) -> None:
    sg_client._find_project = MagicMock(  # type: ignore[method-assign]
        return_value={"id": 456, "name": "ExistingShow"}
    )
    sg_client._create_project = MagicMock()  # type: ignore[method-assign]

    project = sg_client.get_or_create_project("ExistingShow")
    sg_client._create_project.assert_not_called()
    assert project["id"] == 456
