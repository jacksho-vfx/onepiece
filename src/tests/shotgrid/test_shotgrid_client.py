"""Tests for the expanded :mod:`libraries.integrations.shotgrid.client` helpers."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest

from libraries.integrations.shotgrid.client import (
    EntityStore,
    HierarchyTemplate,
    RetryPolicy,
    ShotgridClient,
    ShotgridOperationError,
    TemplateNode,
    TEntity,
)


@pytest.fixture
def sg_client() -> ShotgridClient:
    return ShotgridClient()


def test_get_or_create_project_creates_new(sg_client: ShotgridClient) -> None:
    sg_client._find_project = MagicMock(return_value=None)
    sg_client._create_project = MagicMock(
        return_value={"id": 123, "name": "TestShow", "template": None}
    )

    project = sg_client.get_or_create_project("TestShow")
    sg_client._create_project.assert_called_once_with("TestShow", template=None)
    assert project["name"] == "TestShow"


def test_get_or_create_project_returns_existing(sg_client: ShotgridClient) -> None:
    sg_client._find_project = MagicMock(
        return_value={"id": 456, "name": "ExistingShow", "template": "episodic"}
    )
    sg_client._create_project = MagicMock()

    project = sg_client.get_or_create_project("ExistingShow")
    sg_client._create_project.assert_not_called()
    assert project["id"] == 456
    assert project["template"] == "episodic"


def test_get_or_create_project_stores_and_returns_template() -> None:
    client = ShotgridClient(sleep=lambda _: None)

    created = client.get_or_create_project("TemplateShow", template="episodic")

    assert created["template"] == "episodic"

    fetched = client.get_or_create_project("TemplateShow", template="other-template")

    assert fetched is created
    assert fetched["template"] == "episodic"


def test_bulk_create_update_delete_entities() -> None:
    client = ShotgridClient(sleep=lambda _: None)

    created = client.bulk_create_entities(
        "Shot",
        [{"code": "shot_001"}, {"code": "shot_002"}],
    )

    assert [entity["code"] for entity in created] == ["shot_001", "shot_002"]

    updated = client.bulk_update_entities(
        "Shot",
        [{"id": created[0]["id"], "code": "shot_001_v2"}],
    )

    assert updated[0]["code"] == "shot_001_v2"

    client.bulk_delete_entities("Shot", [created[1]["id"]])

    with pytest.raises(ShotgridOperationError):
        client.bulk_update_entities(
            "Shot", [{"id": created[1]["id"], "code": "missing"}]
        )


def test_entity_store_next_id_handles_sparse_ids() -> None:
    store = EntityStore()
    store.add("Shot", {"id": 1, "type": "Shot"})
    store.add("Shot", {"id": 2, "type": "Shot"})
    store.add("Shot", {"id": 3, "type": "Shot"})

    store.delete("Shot", 2)

    assert store.next_id("Shot") == 4


@dataclass
class FlakyStore(EntityStore):  # type: ignore[misc]
    """Entity store that fails the first ``add`` invocation."""

    attempts: int = 0

    def add(self, entity_type: str, entity: TEntity) -> TEntity:
        self.attempts += 1
        if self.attempts < 2:
            raise RuntimeError("transient failure")
        return cast(TEntity, super().add(entity_type, entity))


def test_bulk_create_retries_transient_failures() -> None:
    store = FlakyStore()
    policy = RetryPolicy(max_attempts=3, base_delay=0, jitter=0)
    client = ShotgridClient(store=store, retry_policy=policy, sleep=lambda _: None)

    created = client.bulk_create_entities("Scene", [{"code": "sc01"}])

    assert created[0]["code"] == "sc01"
    assert store.attempts == 2


def test_apply_hierarchy_template_creates_all_nodes() -> None:
    template = HierarchyTemplate(
        name="episodic",
        roots=(
            TemplateNode(
                "Episode",
                {"code": "ep001"},
                children=(
                    TemplateNode("Scene", {"code": "sc001"}, children=()),
                    TemplateNode("Scene", {"code": "sc002"}, children=()),
                ),
            ),
        ),
    )

    client = ShotgridClient(sleep=lambda _: None)

    result = client.apply_hierarchy_template("Cool Project", template)

    project = client.get_or_create_project("Cool Project")

    assert "Episode" in result
    assert "Scene" in result
    assert {node["code"] for node in result["Episode"]} == {"ep001"}
    assert {node["code"] for node in result["Scene"]} == {"sc001", "sc002"}
    assert all(node["project_id"] == project["id"] for node in result["Scene"])


def test_get_approved_versions_filters_episodes_case_insensitively(
    tmp_path: Path,
) -> None:
    client = ShotgridClient(sleep=lambda _: None)

    media = tmp_path / "clip.mov"
    media.write_bytes(b"data")

    client.register_version(
        "Project X",
        "SHOW_EP01_SC001_SH010_COMP",
        media,
        description="Episode 1",
    )
    client.register_version(
        "Project X",
        "SHOW_EP02_SC010_SH020_COMP",
        media,
        description="Episode 2",
    )

    filtered = client.get_approved_versions("Project X", ["ep01", "  EP02  "])

    shots = [entry["shot"] for entry in filtered]
    assert shots == ["SHOW_EP01_SC001_SH010_COMP", "SHOW_EP02_SC010_SH020_COMP"]


def test_list_versions_for_shot_filters_project_shot_and_status(
    tmp_path: Path,
) -> None:
    client = ShotgridClient(sleep=lambda _: None)

    media = tmp_path / "clip.mov"
    media.write_bytes(b"data")

    approved = client.register_version("Project X", "SH010", media)
    published = client.register_version("Project X", "SH010", media)
    different_shot = client.register_version("Project X", "SH020", media)
    other_project = client.register_version("Project Y", "SH010", media)

    client.bulk_update_entities(
        "Version",
        [
            {"id": approved["id"], "status": "apr"},
            {"id": published["id"], "status": "pub"},
            {"id": different_shot["id"], "status": "apr"},
            {"id": other_project["id"], "status": "apr"},
        ],
    )

    all_versions = client.list_versions_for_shot("Project X", "SH010")
    assert [version["id"] for version in all_versions] == [
        approved["id"],
        published["id"],
    ]

    filtered = client.list_versions_for_shot(
        "Project X", "SH010", statuses=["APR", None]
    )
    assert [version["id"] for version in filtered] == [approved["id"]]

    empty = client.list_versions_for_shot("Project X", "SH010", statuses=["rev"])
    assert empty == []

    missing_shot = client.list_versions_for_shot("Project X", "SH999")
    assert missing_shot == []
