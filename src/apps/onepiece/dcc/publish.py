"""CLI command for publishing packaged scene outputs."""

import json
from pathlib import Path
from typing import Literal, cast, Any

import structlog
import typer

from libraries.dcc.dcc_client import (
    DCCAssetStatus,
    DCCDependencyReport,
    DCCPluginStatus,
    JSONValue,
    publish_scene,
)
from libraries.dcc.maya.unreal_export_checker import UnrealExportReport
from libraries.validations.dcc import validate_dcc


log = structlog.get_logger(__name__)

app = typer.Typer(help="DCC CLI commands.")


def _load_metadata(path: Path) -> dict[str, JSONValue]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:  # pragma: no cover - surfaced to CLI.
        raise typer.BadParameter(f"Invalid metadata JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise typer.BadParameter("Metadata JSON must contain an object")
    return cast(dict[str, JSONValue], data)


def _resolve_dcc(dcc_name: str) -> Any:
    try:
        return validate_dcc(dcc_name)
    except ValueError as exc:  # pragma: no cover - surfaced to CLI.
        raise typer.BadParameter(str(exc)) from exc


def _validate_show_type(show_type: str) -> Literal["vfx", "prod"]:
    lowered = show_type.lower()
    if lowered not in {"vfx", "prod"}:
        raise typer.BadParameter("show-type must be either 'vfx' or 'prod'")
    return lowered  # type: ignore[return-value]


def _validate_direct_upload_path(path: str | None) -> str | None:
    if path is None:
        return None
    if not path.startswith("s3://"):
        raise typer.BadParameter("direct-upload-path must start with 's3://'")
    return path


def _format_dependency_summary(report: DCCDependencyReport) -> str:
    def _join_plugins(status: DCCPluginStatus, attribute: str) -> str:
        value = getattr(status, attribute)
        return ", ".join(sorted(value)) if value else "None"

    def _join_assets(status: DCCAssetStatus, attribute: str) -> str:
        entries = getattr(status, attribute)
        if not entries:
            return "None"
        return ", ".join(sorted(entries))

    lines = [
        f"Dependency summary for {report.dcc.value}",
        f"  Plugins required: {_join_plugins(report.plugins, 'required')}",
        f"  Plugins available: {_join_plugins(report.plugins, 'available')}",
        f"  Plugins missing: {_join_plugins(report.plugins, 'missing')}",
        f"  Assets required: {_join_assets(report.assets, 'required')}",
        f"  Assets present: {_join_assets(report.assets, 'present')}",
        f"  Assets missing: {_join_assets(report.assets, 'missing')}",
    ]
    return "\n".join(lines)


def _format_maya_unreal_summary(report: UnrealExportReport) -> str:
    def _yes_no(flag: bool) -> str:
        return "Yes" if flag else "No"

    lines = [
        f"Maya Unreal export validation for {report.asset_name}",
        f"  Scale valid: {_yes_no(report.scale_valid)}",
        f"  Skeleton valid: {_yes_no(report.skeleton_valid)}",
        f"  Naming valid: {_yes_no(report.naming_valid)}",
    ]

    if report.issues:
        lines.append("  Issues:")
        for issue in report.issues:
            lines.append(f"    - [{issue.severity}] {issue.code}: {issue.message}")
    else:
        lines.append("  Issues: None")

    return "\n".join(lines)


@app.command("publish")
def publish(
    dcc: str = typer.Option(..., "--dcc", help="DCC that produced the scene."),
    scene_name: str = typer.Option(
        ..., "--scene-name", help="Name used for the published package."
    ),
    renders: Path = typer.Option(
        ..., "--renders", exists=True, file_okay=True, dir_okay=True
    ),
    previews: Path = typer.Option(
        ..., "--previews", exists=True, file_okay=True, dir_okay=True
    ),
    otio: Path = typer.Option(..., "--otio", exists=True, file_okay=True),
    metadata: Path = typer.Option(
        ..., "--metadata", exists=True, file_okay=True, dir_okay=False
    ),
    destination: Path = typer.Option(
        ..., "--destination", dir_okay=True, file_okay=False, writable=True
    ),
    bucket: str = typer.Option(..., "--bucket", help="Target S3 bucket."),
    show_code: str = typer.Option(
        ..., "--show-code", help="Show code used in the S3 path."
    ),
    show_type: str = typer.Option(
        "vfx", "--show-type", help="Show type: 'vfx' (vendor) or 'prod'."
    ),
    profile: str | None = typer.Option(
        None, "--profile", help="Optional AWS CLI profile to use."
    ),
    direct_upload_path: str | None = typer.Option(
        None,
        "--direct-upload-path",
        help="Optional full S3 path for direct uploads.",
        callback=_validate_direct_upload_path,
    ),
    dependency_summary: bool = typer.Option(
        False,
        "--dependency-summary/--no-dependency-summary",
        help="Print dependency validation summary after publishing.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Synchronise to S3 without uploading new files.",
    ),
) -> None:
    """Package a scene and publish it to S3."""

    resolved_dcc = _resolve_dcc(dcc)
    resolved_show_type = _validate_show_type(show_type)
    metadata_dict = _load_metadata(metadata)

    report: DCCDependencyReport | None = None
    maya_report: UnrealExportReport | None = None

    def capture_report(dependency_report: DCCDependencyReport) -> None:
        nonlocal report
        report = dependency_report

    def capture_maya_report(unreal_report: UnrealExportReport) -> None:
        nonlocal maya_report
        maya_report = unreal_report

    try:
        package_path = publish_scene(
            resolved_dcc,
            scene_name=scene_name,
            renders=renders,
            previews=previews,
            otio=otio,
            metadata=metadata_dict,
            destination=destination,
            bucket=bucket,
            show_code=show_code,
            show_type=resolved_show_type,
            profile=profile,
            direct_s3_path=direct_upload_path,
            dependency_callback=capture_report if dependency_summary else None,
            maya_validation_callback=(
                capture_maya_report if dependency_summary else None
            ),
            dry_run=dry_run,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--scene-name") from exc

    log.info("cli_publish_completed", package=str(package_path))
    typer.echo(f"Published package created at {package_path}")

    if dependency_summary:
        if report is not None:
            typer.echo(_format_dependency_summary(report))
        if maya_report is not None:
            typer.echo("")
            typer.echo(_format_maya_unreal_summary(maya_report))
