from __future__ import annotations

import json
from pathlib import Path

from libraries.pipeline.ingest import (
    IngestConfig,
    LinkRuleConfig,
    ingest_asset,
    register_hook,
)
from libraries.pipeline.ingest.hooks import IngestContext, run_hooks


class RecordingHook:
    name = "recording"

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def run(self, context: IngestContext, config: dict[str, str]) -> None:
        self._events.append(f"{self.name}:{context.asset_id}")


class RecordingHookTwo:
    name = "recording_two"

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def run(self, context: IngestContext, config: dict[str, str]) -> None:
        self._events.append(f"{self.name}:{context.asset_id}")


def test_ingest_metadata_generation(tmp_path: Path) -> None:
    source = tmp_path / "plate.exr"
    source.write_text("pixels")
    config = IngestConfig(
        link_rules=(
            LinkRuleConfig(
                name="plates", target="assets/plates", match_any_tags=("plates",)
            ),
        )
    )

    result = ingest_asset(
        source=source,
        project_root=tmp_path,
        config=config,
        asset_id="asset-001",
        tags=["plates"],
    )

    metadata = json.loads(result.metadata_path.read_text())
    assert metadata["asset_id"] == "asset-001"
    assert metadata["source_uri"].endswith("plate.exr")
    assert metadata["files"][0]["sha256"]
    assert metadata["tags"]["freeform"] == ["plates"]
    assert metadata["schema_version"] == "1.1"
    assert metadata["payload_hash"]
    assert metadata["payload_size_bytes"] > 0


def test_link_resolution_and_conflict(tmp_path: Path) -> None:
    source = tmp_path / "model.fbx"
    source.write_text("mesh")
    config = IngestConfig(
        link_rules=(
            LinkRuleConfig(
                name="geo",
                target="assets/geo",
                name_template="{basename}",
                match_any_tags=("geo",),
            ),
        )
    )
    conflict_path = tmp_path / "assets" / "geo" / source.name
    conflict_path.parent.mkdir(parents=True)
    conflict_path.write_text("existing")

    result = ingest_asset(
        source=source,
        project_root=tmp_path,
        config=config,
        asset_id="asset-1234567890",
        tags=["geo"],
    )

    assert result.links
    created_link = result.links[0]
    assert created_link.destination.name.startswith("model__asset123")
    assert created_link.destination.exists()


def test_hooks_run_in_order_and_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "plate.exr"
    source.write_text("pixels")
    config = IngestConfig(
        link_rules=(
            LinkRuleConfig(
                name="plates", target="assets/plates", match_any_tags=("plates",)
            ),
        )
    )

    events: list[str] = []
    register_hook(RecordingHook(events))
    register_hook(RecordingHookTwo(events))

    result = ingest_asset(
        source=source,
        project_root=tmp_path,
        config=config,
        asset_id="asset-hook",
        tags=["plates"],
    )

    context = IngestContext(
        asset_id=result.asset_id,
        asset_dir=result.asset_dir,
        metadata_path=result.metadata_path,
        project_root=tmp_path,
    )

    run_hooks(
        context,
        [
            {"name": "recording", "config": {}},
            {"name": "recording_two", "config": {}},
        ],
    )
    run_hooks(
        context,
        [
            {"name": "recording", "config": {}},
            {"name": "recording_two", "config": {}},
        ],
    )

    assert events == ["recording:asset-hook", "recording_two:asset-hook"]
