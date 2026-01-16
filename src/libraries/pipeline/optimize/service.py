"""Optimization orchestration helpers."""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

from libraries.pipeline.ingest.metadata import (
    IngestMetadata,
    IngestMetadataFile,
    now_timestamp,
)
from libraries.pipeline.optimize.config import OptimizationConfig, VariantConfig
from libraries.pipeline.optimize.handlers.base import HandlerContext, HandlerResult
from libraries.pipeline.optimize.handlers.caches import (
    optimize_caches,
)
from libraries.pipeline.optimize.handlers.caches import supports as caches_support
from libraries.pipeline.optimize.handlers.textures import (
    optimize_textures,
)
from libraries.pipeline.optimize.handlers.textures import supports as textures_support
from libraries.pipeline.optimize.handlers.three_d import (
    optimize_model,
)
from libraries.pipeline.optimize.handlers.three_d import supports as model_support
from libraries.pipeline.optimize.report import OptimizationReport, OptimizationStep


@dataclass(frozen=True)
class OptimizationPlan:
    variant: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class OptimizationRunResult:
    variant: str
    report_path: Path
    output_root: Path
    status: str


def derived_root(project_root: Path, asset_id: str, variant: str) -> Path:
    return project_root / ".pipeline" / "derived" / asset_id / variant


def _metadata_path(project_root: Path, asset_id: str) -> Path:
    return project_root / ".pipeline" / "ingest" / asset_id / "metadata.json"


def load_metadata(
    project_root: Path, asset_id: str
) -> tuple[IngestMetadata, Path, Path]:
    metadata_path = _metadata_path(project_root, asset_id)
    metadata = IngestMetadataFile(metadata_path).read()
    asset_dir = metadata_path.parent
    payload_root = asset_dir / metadata.payload_name
    if not payload_root.exists():
        raise FileNotFoundError(f"Payload root not found: {payload_root}")
    return metadata, asset_dir, payload_root


def _list_handlers(
    asset_types: Iterable[str],
    variant: VariantConfig,
) -> list[tuple[str, dict[str, Any]]]:
    handlers: list[tuple[str, dict[str, Any]]] = []
    if model_support(asset_types) and "3d" in variant.handlers:
        handlers.append(("3d", variant.handlers["3d"]))
    if textures_support(asset_types) and "texture" in variant.handlers:
        handlers.append(("texture", variant.handlers["texture"]))
    if caches_support(asset_types) and "cache" in variant.handlers:
        handlers.append(("cache", variant.handlers["cache"]))
    return handlers


def plan_variants(
    *,
    metadata: IngestMetadata,
    config: OptimizationConfig,
) -> tuple[OptimizationPlan, ...]:
    plans: list[OptimizationPlan] = []
    for name, variant in sorted(config.variants.items()):
        if not variant.enabled:
            continue
        steps: list[str] = []
        handlers = _list_handlers(metadata.file_types, variant)
        for handler_name, settings in handlers:
            if handler_name == "3d":
                steps.extend(
                    [
                        "clean_geometry",
                        "merge_materials",
                        "fix_normals",
                        "strip_junk_nodes",
                        "generate_lods",
                        "decimate",
                        "normalize_scene",
                        "copy_textures",
                    ]
                )
                if settings.get("convert_to_usd"):
                    steps.append("convert_to_usd")
            if handler_name == "texture":
                steps.append("optimize_textures")
                if settings.get("tile"):
                    steps.append("tile_textures")
                if settings.get("generate_mips"):
                    steps.append("generate_mips")
            if handler_name == "cache":
                steps.append("validate_frames")
                if settings.get("proxy"):
                    steps.append("generate_proxy")
        plans.append(OptimizationPlan(variant=name, steps=tuple(steps)))
    return tuple(plans)


def _tool_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    if shutil.which("usdcat"):
        versions["usdcat"] = "available"
    if shutil.which("usd_from_gltf"):
        versions["usd_from_gltf"] = "available"
    if shutil.which("usd_from_fbx"):
        versions["usd_from_fbx"] = "available"
    if shutil.which("usd_from_obj"):
        versions["usd_from_obj"] = "available"
    return versions


def _collect_output_size(output_root: Path) -> int:
    total = 0
    if not output_root.exists():
        return 0
    for path in output_root.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def _write_report(report: OptimizationReport, report_path: Path) -> None:
    import json

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    )


def _merge_results(results: list[HandlerResult]) -> HandlerResult:
    merged = HandlerResult()
    for result in results:
        merged.steps.extend(result.steps)
        merged.metrics.update(result.metrics)
        merged.warnings.extend(result.warnings)
        merged.errors.extend(result.errors)
        merged.output_files.extend(result.output_files)
    return merged


def _update_metadata(
    metadata_path: Path,
    metadata: IngestMetadata,
    variant: str,
    report_path: Path,
    output_root: Path,
    status: str,
) -> None:
    variant_entry = {
        "variant": variant,
        "path": str(output_root),
        "report_path": str(report_path),
        "status": status,
        "timestamp": now_timestamp(),
    }
    derived = [
        entry
        for entry in metadata.derived_variants
        if isinstance(entry, dict) and entry.get("variant") != variant
    ]
    derived.append(variant_entry)
    preferred_variant = _best_available_variant(derived)
    updated = IngestMetadata(
        schema_version=metadata.schema_version,
        asset_id=metadata.asset_id,
        source_uri=metadata.source_uri,
        ingest_timestamp=metadata.ingest_timestamp,
        payload_name=metadata.payload_name,
        payload_hash=metadata.payload_hash,
        payload_size_bytes=metadata.payload_size_bytes,
        files=metadata.files,
        tags=metadata.tags,
        file_types=metadata.file_types,
        capabilities=metadata.capabilities,
        user=metadata.user,
        machine=metadata.machine,
        relationships=metadata.relationships,
        derived_variants=derived,
        preferred_variant=preferred_variant,
    )
    IngestMetadataFile(metadata_path).write(updated)


def run_variant(
    *,
    metadata: IngestMetadata,
    metadata_path: Path,
    payload_root: Path,
    project_root: Path,
    variant: VariantConfig,
    dry_run: bool = False,
) -> OptimizationRunResult:
    output_root = derived_root(project_root, metadata.asset_id, variant.name)
    report_path = output_root / "opt_report.json"
    if dry_run:
        return OptimizationRunResult(
            variant=variant.name,
            report_path=report_path,
            output_root=output_root,
            status="dry-run",
        )
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    tags = set(metadata.tags.get("freeform", [])) | set(
        metadata.tags.get("controlled", [])
    )
    handler_results: list[HandlerResult] = []
    for handler_name, settings in _list_handlers(metadata.file_types, variant):
        context = HandlerContext(
            project_root=project_root,
            asset_id=metadata.asset_id,
            payload_root=payload_root,
            output_root=output_root / handler_name,
            variant=variant.name,
            settings=settings,
            tags=tags,
            metadata_path=metadata_path,
        )
        if handler_name == "3d":
            handler_results.append(optimize_model(context))
        elif handler_name == "texture":
            handler_results.append(optimize_textures(context))
        elif handler_name == "cache":
            handler_results.append(optimize_caches(context))
    merged = _merge_results(handler_results)
    merged.steps.insert(
        0,
        OptimizationStep(
            name="detected_handlers",
            status="ok",
            detail=", ".join(
                name for name, _ in _list_handlers(metadata.file_types, variant)
            )
            or "none",
        ),
    )

    report = OptimizationReport(
        schema_version="1.0",
        asset_id=metadata.asset_id,
        variant=variant.name,
        input_path=str(payload_root),
        input_hash=metadata.payload_hash,
        input_size_bytes=metadata.payload_size_bytes,
        output_path=str(output_root),
        output_size_bytes=_collect_output_size(output_root),
        settings={
            handler: settings
            for handler, settings in _list_handlers(metadata.file_types, variant)
        },
        tool_versions=_tool_versions(),
        metrics=merged.metrics,
        steps=merged.steps,
        warnings=merged.warnings,
        errors=merged.errors,
    )
    _write_report(report, report_path)
    status = "error" if merged.errors else "success"
    _update_metadata(
        metadata_path, metadata, variant.name, report_path, output_root, status
    )
    return OptimizationRunResult(
        variant=variant.name,
        report_path=report_path,
        output_root=output_root,
        status=status,
    )


def _best_available_variant(derived_variants: Iterable[dict[str, Any]]) -> str:
    variants = {
        str(entry.get("variant"))
        for entry in derived_variants
        if isinstance(entry, dict)
    }
    for candidate in ("usd", "optimized", "proxy"):
        if candidate in variants:
            return candidate
    return "canonical"


def load_report(report_path: Path) -> dict[str, Any]:
    import json

    return cast(dict[str, Any], json.loads(report_path.read_text()))
