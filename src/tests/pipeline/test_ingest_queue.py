from __future__ import annotations

import textwrap
from pathlib import Path

from libraries.pipeline.ingest.executor import (
    PROGRESS_COPY,
    PROGRESS_INDEX,
    PROGRESS_META,
    execute_queue_item,
    load_progress,
)
from libraries.pipeline.ingest.inventory import load_asset_record, rebuild_index
from libraries.pipeline.ingest.metadata import IngestMetadataFile, now_timestamp
from libraries.pipeline.ingest.queue import IngestQueueItem
from libraries.pipeline.ingest.rules import load_ingest_rules, plan_ingest
from libraries.pipeline.ingest.tagging import infer_tags


def _write_rules(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            schema_version: 1
            rules:
              - name: plates
                priority: 10
                match:
                  any_tags: [plates, dept:plates]
                  file_types: [image]
                outputs:
                  - target: assets/plates
                    name_template: "{basename}"
            """
        ).strip()
        + "\n"
    )


def test_tag_inference_from_path_and_extension(tmp_path: Path) -> None:
    source = tmp_path / "plates" / "shot01" / "plate.exr"
    source.parent.mkdir(parents=True)
    source.write_text("pixels")

    tags = infer_tags(source)

    assert "plates" in tags["freeform"]
    assert "dept:plates" in tags["controlled"]
    assert "ext:exr" in tags["controlled"]


def test_rule_matching_order(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        textwrap.dedent(
            """
            schema_version: 1
            rules:
              - name: late
                priority: 20
                match:
                  any_tags: [plates]
                outputs:
                  - target: assets/late
              - name: early
                priority: 10
                match:
                  any_tags: [plates]
                outputs:
                  - target: assets/early
            """
        ).strip()
        + "\n"
    )
    rules = load_ingest_rules(rules_path)
    plan = plan_ingest(
        rules=rules,
        tags={"plates"},
        file_types={"image"},
        extensions={".exr"},
        source_path="/plates/shot01/plate.exr",
        payload_size_bytes=10,
    )

    assert [link.rule_name for link in plan.links] == ["early", "late"]


def test_resume_execution_updates_index(tmp_path: Path) -> None:
    project_root = tmp_path
    rules_path = project_root / ".pipeline" / "ingest_rules.yaml"
    rules_path.parent.mkdir(parents=True)
    _write_rules(rules_path)

    source = project_root / "plates" / "shot01" / "plate.exr"
    source.parent.mkdir(parents=True)
    source.write_text("pixels")

    item = IngestQueueItem(
        item_id="item-1",
        session_id="session-1",
        source=source.as_posix(),
        status="queued",
        created_at=now_timestamp(),
        tags=["plates"],
        controlled_tags=[],
        rules_path=None,
        config_path=None,
        asset_id="asset-1",
    )

    result = execute_queue_item(
        item=item,
        project_root=project_root,
        resume=False,
        force=False,
    )
    progress = load_progress(result.asset_dir)
    assert PROGRESS_COPY in progress
    assert PROGRESS_META in progress
    assert PROGRESS_INDEX in progress

    metadata_path = result.metadata_path
    metadata = IngestMetadataFile(metadata_path).read()

    result_second = execute_queue_item(
        item=item,
        project_root=project_root,
        resume=True,
        force=False,
    )
    metadata_second = IngestMetadataFile(result_second.metadata_path).read()

    assert metadata.ingest_timestamp == metadata_second.ingest_timestamp

    rebuild_index(project_root)
    record = load_asset_record(project_root, result_second.asset_id)
    assert record.payload_name == source.name
