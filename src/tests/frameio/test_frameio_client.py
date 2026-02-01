from pathlib import Path
import pytest

from libraries.integrations.frameio.client import (
    EntityStore,
    FrameioClient,
    FrameioOperationError,
    HierarchyTemplate,
    RetryPolicy,
    TemplateNode,
)


def test_register_asset_creates_project_and_folders(tmp_path: Path) -> None:
    client = FrameioClient()
    asset = client.register_asset(
        "demo",
        tmp_path / "plate.mov",
        folder_path="Episode 01/SeqA",
        description="Delivery",
        team="Editorial",
    )

    assert asset["project"] == "demo"
    assert asset["folder_path"] == "Episode 01/SeqA"
    assert asset["description"] == "Delivery"

    folder = client.list_assets_for_folder("demo", "Episode 01/SeqA")
    assert len(folder) == 1
    assert folder[0]["name"] == "plate"


def test_list_assets_for_unknown_folder_returns_empty(tmp_path: Path) -> None:
    client = FrameioClient()
    client.register_asset("demo", tmp_path / "plate.mov")

    assert client.list_assets_for_folder("demo", "nope") == []


def test_review_links_merge_assets(tmp_path: Path) -> None:
    client = FrameioClient()
    first = client.register_asset("demo", tmp_path / "plate.mov")
    second = client.register_asset("demo", tmp_path / "plate_v2.mov")

    link = client.ensure_review_link("demo", "Client Review", [first["id"]])
    updated = client.ensure_review_link(
        "demo", "Client Review", [second["id"], first["id"]]
    )

    assert link["id"] == updated["id"]
    assert sorted(updated["asset_ids"]) == sorted({first["id"], second["id"]})


def test_hierarchy_template_round_trip(tmp_path: Path) -> None:
    client = FrameioClient()
    template = HierarchyTemplate(
        name="frameio-default",
        roots=(
            TemplateNode(
                "Folder",
                {"name": "Project Root"},
                children=(
                    TemplateNode("Folder", {"name": "Dailies"}),
                    TemplateNode("Folder", {"name": "Masters"}),
                ),
            ),
        ),
    )

    destination = tmp_path / "template.yaml"
    client.save_hierarchy_template(template, destination)

    loaded = client.load_hierarchy_template(destination)
    assert loaded.to_dict() == template.to_dict()

    created = client.apply_hierarchy_template("demo", loaded)
    assert "Folder" in created
    assert len(created["Folder"]) == 3


def test_bulk_helpers_retry_and_update() -> None:
    attempts: list[float] = []

    def record_sleep(delay: float) -> None:
        attempts.append(delay)

    noisy_store = EntityStore()

    def boom(_: str, __: int) -> None:
        raise RuntimeError("boom")

    noisy_store.delete = boom  # type: ignore[assignment]

    client = FrameioClient(
        store=noisy_store,
        retry_policy=RetryPolicy(max_attempts=2),
        sleep=record_sleep,
    )

    with pytest.raises(FrameioOperationError):
        client.bulk_delete_entities("Asset", [1])

    assert attempts  # ensure retry attempted

    store = EntityStore()
    client = FrameioClient(store=store)
    created = client.bulk_create_entities("Asset", [{"name": "clip", "path": "a.mov"}])[
        0
    ]
    updated = client.bulk_update_entities(
        "Asset", [{"id": created["id"], "description": "updated"}]
    )
    assert updated[0]["description"] == "updated"
