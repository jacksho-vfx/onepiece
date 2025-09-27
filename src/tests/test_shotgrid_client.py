"""Tests for the expanded :mod:`libraries.shotgrid.client` helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from src.libraries.shotgrid.client import (
    EntityStore,
    HierarchyTemplate,
    RetryPolicy,
    ShotgridClient,
    ShotgridOperationError,
    TemplateNode,
    TEntity,
)


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


@dataclass
class FlakyStore(EntityStore):
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
