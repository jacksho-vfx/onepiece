from __future__ import annotations

from pathlib import Path

import json

from libraries.pipeline.ingest.metadata import (
    IngestMetadata,
    IngestMetadataFile,
    SCHEMA_VERSION,
)
from libraries.pipeline.ingest.payload import build_payload_manifest
from libraries.pipeline.ingest.rules import load_ingest_rules, plan_ingest
from libraries.pipeline.optimize.config import load_optimize_config
from libraries.pipeline.optimize.service import derived_root, run_variant


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _create_asset(project_root: Path) -> tuple[str, Path, Path]:
    asset_id = "asset-001"
    asset_dir = project_root / ".pipeline" / "ingest" / asset_id
    payload_root = asset_dir / "payload"
    payload_root.mkdir(parents=True, exist_ok=True)
    _write_text(payload_root / "model.obj", "o mesh\nv 0 0 0\nf 1 1 1\n")
    manifest = build_payload_manifest(payload_root)
    metadata = IngestMetadata(
        schema_version=SCHEMA_VERSION,
        asset_id=asset_id,
        source_uri=payload_root.as_posix(),
        ingest_timestamp="2024-01-01T00:00:00+00:00",
        payload_name=manifest.payload_name,
        payload_hash=manifest.payload_hash,
        payload_size_bytes=manifest.payload_size_bytes,
        files=manifest.files,
        tags={"freeform": ["asset_type:model"], "controlled": []},
        file_types=manifest.file_types,
        capabilities=manifest.capabilities,
        user={},
        machine={},
        relationships=[],
        derived_variants=[],
        preferred_variant=None,
    )
    IngestMetadataFile(asset_dir / "metadata.json").write(metadata)
    return asset_id, asset_dir, payload_root


def test_type_detection_records_capabilities(tmp_path: Path) -> None:
    payload_root = tmp_path / "payload"
    payload_root.mkdir(parents=True, exist_ok=True)
    _write_text(payload_root / "mesh.fbx", "fbx")
    _write_text(payload_root / "texture.png", "png")
    _write_text(payload_root / "cache.abc", "abc")
    manifest = build_payload_manifest(payload_root)
    assert "3d_model" in manifest.file_types
    assert "cache" in manifest.file_types
    assert "texture" in manifest.file_types
    assert manifest.capabilities["3d_model"]["can_optimize"] is True


def test_derived_path_is_deterministic(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    assert (
        derived_root(project_root, "asset-001", "optimized")
        == project_root / ".pipeline" / "derived" / "asset-001" / "optimized"
    )


def test_rules_trigger_optimize_actions(tmp_path: Path) -> None:
    rules_path = tmp_path / "rules.yaml"
    rules_path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "rules:",
                "  - name: usd",
                "    priority: 1",
                "    match:",
                "      any_tags: [asset_type:model]",
                "    actions:",
                "      optimize:",
                "        - variant: usd",
                "          mode: deadline",
            ]
        )
    )
    rules = load_ingest_rules(rules_path)
    plan = plan_ingest(
        rules=rules,
        tags={"asset_type:model"},
        file_types={"3d_model"},
        extensions={".fbx"},
        source_path="/assets/hero",
        payload_size_bytes=100,
    )
    assert plan.optimize_actions
    assert plan.optimize_actions[0].variant == "usd"
    assert plan.optimize_actions[0].mode == "deadline"


def test_report_generation_and_idempotency(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    asset_id, asset_dir, payload_root = _create_asset(project_root)
    config = load_optimize_config(project_root=project_root)
    metadata_path = asset_dir / "metadata.json"
    metadata = IngestMetadataFile(metadata_path).read()

    result = run_variant(
        metadata=metadata,
        metadata_path=metadata_path,
        payload_root=payload_root,
        project_root=project_root,
        variant=config.variants["optimized"],
        dry_run=False,
    )
    report = json.loads(result.report_path.read_text())
    assert report["asset_id"] == asset_id
    assert report["variant"] == "optimized"
    assert "input" in report and "output" in report

    run_variant(
        metadata=metadata,
        metadata_path=metadata_path,
        payload_root=payload_root,
        project_root=project_root,
        variant=config.variants["optimized"],
        dry_run=False,
    )
    updated_metadata = IngestMetadataFile(metadata_path).read()
    variants = [
        entry
        for entry in updated_metadata.derived_variants
        if entry.get("variant") == "optimized"
    ]
    assert len(variants) == 1
    assert updated_metadata.preferred_variant in {
        "optimized",
        "usd",
        "proxy",
        "canonical",
    }
