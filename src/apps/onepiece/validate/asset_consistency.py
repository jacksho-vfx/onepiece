"""CLI helpers for validating asset consistency across storage backends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import structlog
import typer

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.validations.asset_consistency import (
    S3ParityReport,
    check_shot_versions_local,
    check_shot_versions_s3,
)

log = structlog.get_logger(__name__)


def _load_manifest(manifest_path: Path) -> Dict[str, List[str]]:
    """Return the shot/version manifest encoded as JSON."""

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:  # pragma: no cover - defensive guard
        raise OnePieceValidationError(f"Manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise OnePieceValidationError(
            f"Manifest must be valid JSON mapping shot names to version lists: {manifest_path}"
        ) from exc

    if not isinstance(payload, dict):
        raise OnePieceValidationError(
            "Manifest must be a JSON object mapping names to versions"
        )

    normalised: Dict[str, List[str]] = {}
    for key, value in payload.items():
        if not isinstance(value, list):
            raise OnePieceValidationError(
                "Manifest entries must be arrays of version strings."
            )
        normalised[str(key)] = [str(item) for item in value]
    return normalised


def _render_missing(title: str, missing: Dict[str, List[str]]) -> None:
    typer.secho(title, fg=typer.colors.YELLOW)
    for shot, versions in sorted(missing.items()):
        version_list = ", ".join(versions)
        typer.secho(f"  - {shot}: missing {version_list}", fg=typer.colors.YELLOW)


def _render_unexpected(unexpected: Dict[str, List[str]]) -> None:
    typer.secho("Unexpected versions present in S3:", fg=typer.colors.MAGENTA)
    for shot, versions in sorted(unexpected.items()):
        version_list = ", ".join(versions)
        typer.secho(f"  - {shot}: {version_list}", fg=typer.colors.MAGENTA)


def _render_s3_report(report: S3ParityReport) -> None:
    if report.missing:
        _render_missing("Versions missing from S3:", report.missing)
    if report.unexpected:
        _render_unexpected(report.unexpected)
    if report.is_clean:
        typer.secho(
            "S3 parity verified – all expected versions are present.",
            fg=typer.colors.GREEN,
        )


def asset_consistency(
    manifest: Path = typer.Argument(
        ..., help="JSON file mapping shot or asset identifiers to version arrays."
    ),
    local_base: Path | None = typer.Option(
        None,
        "--local-base",
        help="Optional filesystem root containing versioned publishes.",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="ShotGrid project name to use when querying S3.",
    ),
    context: str | None = typer.Option(
        None,
        "--context",
        help="S3 context to scan (vendor_in, vendor_out, client_in, client_out).",
    ),
    scope: str = typer.Option(
        "shots",
        "--scope",
        help="Entity scope for the manifest (shots or assets).",
        case_sensitive=False,
        show_default=True,
    ),
) -> None:
    """Validate version parity across local storage and S3."""

    data = _load_manifest(manifest)
    scope_value = scope.lower()
    if scope_value not in {"shots", "assets"}:
        raise OnePieceValidationError("Scope must be either 'shots' or 'assets'.")

    typer.secho(f"Loaded manifest with {len(data)} entries", fg=typer.colors.CYAN)

    failures = False

    if local_base is not None:
        missing_local = check_shot_versions_local(data, local_base)
        if missing_local:
            failures = True
            _render_missing("Versions missing locally:", missing_local)
        else:
            typer.secho(
                "Local parity verified – all expected versions are present.",
                fg=typer.colors.GREEN,
            )

    if project is None and context is not None:
        raise OnePieceValidationError(
            "--project must be provided when --context is set."
        )
    if context is None and project is not None:
        raise OnePieceValidationError(
            "--context must be provided when --project is set."
        )

    if project and context:
        s3_report = check_shot_versions_s3(data, project, context, scope=scope_value)
        _render_s3_report(s3_report)
        if not s3_report.is_clean:
            failures = True

    if not failures:
        typer.secho("Asset consistency checks passed.", fg=typer.colors.GREEN)
        log.info(
            "validate.asset_consistency.success",
            manifest=str(manifest),
            local_base=str(local_base) if local_base else None,
            project=project,
            context=context,
            scope=scope_value,
        )
        return

    log.warning(
        "validate.asset_consistency.failures",
        manifest=str(manifest),
        local_base=str(local_base) if local_base else None,
        project=project,
        context=context,
        scope=scope_value,
    )
    raise OnePieceValidationError(
        "Discrepancies detected. Review the missing and unexpected versions above."
    )


__all__ = ["asset_consistency"]
