"""Optimization CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer

from apps.onepiece.config import load_profile
from libraries.pipeline.ingest.metadata import (
    SCHEMA_VERSION,
    IngestMetadata,
    IngestMetadataFile,
    now_timestamp,
)
from libraries.pipeline.ingest.payload import build_payload_manifest
from libraries.pipeline.optimize.config import load_optimize_config
from libraries.pipeline.optimize.deadline import build_deadline_job, submit_deadline_job
from libraries.pipeline.optimize.service import (
    load_metadata,
    load_report,
    plan_variants,
    run_variant,
)


def _resolve_project_root(project_root: Path) -> Path:
    return project_root.expanduser().resolve()


def _resolve_metadata(
    project_root: Path, asset_or_path: str
) -> tuple[str, IngestMetadata]:
    asset_root = project_root / ".pipeline" / "ingest" / asset_or_path
    if asset_root.exists():
        metadata_path = asset_root / "metadata.json"
        return asset_or_path, IngestMetadataFile(metadata_path).read()
    source = Path(asset_or_path).expanduser().resolve()
    manifest = build_payload_manifest(source)
    metadata = IngestMetadata(
        schema_version=SCHEMA_VERSION,
        asset_id=asset_or_path,
        source_uri=source.as_posix(),
        ingest_timestamp=now_timestamp(),
        payload_name=manifest.payload_name,
        payload_hash=manifest.payload_hash,
        payload_size_bytes=manifest.payload_size_bytes,
        files=manifest.files,
        tags={"freeform": [], "controlled": []},
        file_types=manifest.file_types,
        capabilities=manifest.capabilities,
        user={},
        machine={},
        relationships=[],
        derived_variants=[],
        preferred_variant=None,
    )
    return asset_or_path, metadata


app = typer.Typer(help="Plan and run asset optimization variants.")


@app.command("plan")
def optimize_plan(
    asset_or_path: str = typer.Argument(
        ..., help="Asset ID or file/folder path to plan."
    ),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Configuration profile to resolve."
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit plan in JSON format."),
) -> None:
    project_root = _resolve_project_root(project_root)
    profile_context = load_profile(profile=profile, project_root=project_root)
    config = load_optimize_config(
        project_root=project_root, profile_data=profile_context.data
    )
    asset_id, metadata = _resolve_metadata(project_root, asset_or_path)
    plans = plan_variants(metadata=metadata, config=config)
    payload: dict[str, Any] = {"asset_id": asset_id, "variants": []}
    for plan in plans:
        payload["variants"].append({"variant": plan.variant, "steps": list(plan.steps)})
    if json_output:
        import json

        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"Plan for {asset_id}:")
    for plan in plans:
        typer.echo(f"  variant={plan.variant}")
        for step in plan.steps:
            typer.echo(f"    - {step}")


@app.command("run")
def optimize_run(
    asset_id: str = typer.Argument(..., help="Asset ID to optimize."),
    variant: str = typer.Option("optimized", "--variant", help="Variant name."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Configuration profile to resolve."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planned output only."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit results in JSON format."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    profile_context = load_profile(profile=profile, project_root=project_root)
    config = load_optimize_config(
        project_root=project_root, profile_data=profile_context.data
    )
    if variant not in config.variants:
        raise typer.BadParameter(f"Unknown variant '{variant}'")
    metadata, _, payload_root = load_metadata(project_root, asset_id)
    metadata_path = project_root / ".pipeline" / "ingest" / asset_id / "metadata.json"
    result = run_variant(
        metadata=metadata,
        metadata_path=metadata_path,
        payload_root=payload_root,
        project_root=project_root,
        variant=config.variants[variant],
        dry_run=dry_run,
    )
    payload = {
        "asset_id": asset_id,
        "variant": result.variant,
        "report_path": str(result.report_path),
        "output_root": str(result.output_root),
        "status": result.status,
    }
    if json_output:
        import json

        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(
        f"Optimization {result.status}: variant={result.variant} "
        f"report={result.report_path}"
    )


@app.command("submit")
def optimize_submit(
    asset_id: str = typer.Argument(..., help="Asset ID to optimize on Deadline."),
    variant: str = typer.Option("optimized", "--variant", help="Variant name."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
    profile: Optional[str] = typer.Option(
        None, "--profile", help="Configuration profile to resolve."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit submission payload in JSON."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    profile_context = load_profile(profile=profile, project_root=project_root)
    config = load_optimize_config(
        project_root=project_root, profile_data=profile_context.data
    )
    if variant not in config.variants:
        raise typer.BadParameter(f"Unknown variant '{variant}'")
    asset_dir = project_root / ".pipeline" / "ingest" / asset_id
    job = build_deadline_job(
        asset_id=asset_id,
        asset_dir=asset_dir,
        variant=variant,
        project_root=project_root,
        config=config.deadline,
    )
    submission = submit_deadline_job(job)
    payload = {
        "asset_id": asset_id,
        "variant": variant,
        "job_info": str(job.job_info_path),
        "plugin_info": str(job.plugin_info_path),
        "submission": submission,
    }
    if json_output:
        import json

        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo(f"Submitted Deadline job for {asset_id} ({variant}): {submission}")


@app.command("report")
def optimize_report(
    asset_id: str = typer.Argument(..., help="Asset ID to inspect."),
    project_root: Path = typer.Option(
        Path("."), "--project-root", help="Project root containing .pipeline."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit report summary in JSON."
    ),
) -> None:
    project_root = _resolve_project_root(project_root)
    metadata_path = project_root / ".pipeline" / "ingest" / asset_id / "metadata.json"
    metadata = IngestMetadataFile(metadata_path).read()
    if not metadata.derived_variants:
        typer.echo("No optimization runs recorded.")
        return
    latest = sorted(
        (entry for entry in metadata.derived_variants if isinstance(entry, dict)),
        key=lambda entry: entry.get("timestamp", ""),
    )[-1]
    report_path = Path(str(latest.get("report_path", "")))
    report_payload = load_report(report_path)
    if json_output:
        import json

        typer.echo(json.dumps(report_payload, indent=2, sort_keys=True))
        return
    typer.echo(f"Latest optimization report: {report_path}")
    typer.echo(f"  variant: {report_payload.get('variant')}")
    typer.echo(f"  status: {latest.get('status')}")
    typer.echo(f"  size_before: {report_payload.get('input', {}).get('size_bytes')}")
    typer.echo(f"  size_after: {report_payload.get('output', {}).get('size_bytes')}")
