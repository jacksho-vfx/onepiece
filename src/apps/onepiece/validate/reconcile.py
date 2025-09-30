"""Typer command to reconcile ShotGrid, filesystem, and S3 state."""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from pathlib import Path
from typing import Literal, Optional

import structlog
import typer

from apps.onepiece.utils.progress import progress_tracker
from libraries.aws.scanner import scan_s3_context
from libraries.filesystem.scanner import scan_project_files
from libraries.reconcile.comparator import (
    collect_shots,
    compare_datasets,
)
from libraries.shotgrid.api import ShotGridClient, ShotGridError

log = structlog.get_logger(__name__)

PROJECT_ROOT_ENV = "ONEPIECE_PROJECTS_ROOT"
DEFAULT_PROJECTS_ROOT = Path("/projects")

ScopeLiteral = Literal["shots", "assets", "versions"]

ScopeOption = typer.Option(
    "shots",
    "--scope",
    help="Area of the project to reconcile.",
    case_sensitive=False,
    show_choices=True,
    show_default=True,
)

app = typer.Typer(name="validate", help="Validate pipeline.")


def _resolve_project_root(project: str) -> Path:
    base = Path(os.environ.get(PROJECT_ROOT_ENV, DEFAULT_PROJECTS_ROOT))
    return base / project


def _write_csv_report(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json_report(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2)


@app.command("reconcile")
def reconcile(
    project: str = typer.Option(..., "--project", help="ShotGrid project name"),
    scope: ScopeLiteral = ScopeOption,
    context: Optional[str] = typer.Option(
        None,
        "--context",
        help="Restrict S3 scan to vendor_in, vendor_out, client_in, or client_out",
    ),
    csv_report: Optional[Path] = typer.Option(
        None,
        "--csv",
        help="Path to write a CSV report of mismatches",
    ),
    json_report: Optional[Path] = typer.Option(
        None,
        "--json",
        help="Path to write a JSON report of mismatches",
    ),
) -> None:
    """Entry point executed by the Typer CLI."""

    if scope not in ("shots", "assets", "versions"):
        raise ValueError(f"Invalid scope: {scope}")
    log.info(
        "reconcile.start",
        project=project,
        scope=scope,
        context=context,
    )

    try:
        sg_client = ShotGridClient.from_env()
        sg_versions = sg_client.get_versions_for_project(project)
    except (ShotGridError, Exception) as exc:
        log.error("reconcile.shotgrid_failed", project=project, error=str(exc))
        raise typer.Exit(code=2) from exc

    project_root = _resolve_project_root(project)
    try:
        fs_versions = scan_project_files(project_root, scope=scope)
    except Exception as exc:  # pragma: no cover - defensive guard
        log.error("reconcile.filesystem_failed", root=str(project_root), error=str(exc))
        raise typer.Exit(code=2) from exc

    s3_versions = None
    if context:
        try:
            s3_versions = scan_s3_context(project, context, scope=scope)
        except Exception as exc:  # pragma: no cover - defensive guard
            log.error(
                "reconcile.s3_failed",
                project=project,
                context=context,
                error=str(exc),
            )
            raise typer.Exit(code=2) from exc

    shots = collect_shots(sg_versions, fs_versions, s3_versions)
    total_shots = len(shots)

    with progress_tracker(
        "Reconcile Project Data",
        total=max(total_shots, 1),
        task_description="Comparing sources",
    ) as reconcile_progress:
        processed = 0

        def _on_progress(step: int) -> None:
            nonlocal processed
            processed += step
            description = (
                f"Compared {processed}/{total_shots} shots"
                if total_shots
                else "Reconciling"
            )
            reconcile_progress.advance(step=step, description=description)

        mismatches = compare_datasets(
            sg_versions,
            fs_versions,
            s3_versions,
            shots=shots,
            progress_callback=_on_progress,
        )

        reconcile_progress.succeed(
            f"Compared {total_shots} shot(s) across ShotGrid, filesystem, and S3."
        )

    totals = Counter(mismatch["type"] for mismatch in mismatches)
    typer.secho(f"Checked {len(shots)} shots", fg=typer.colors.CYAN)
    if mismatches:
        typer.secho("Discrepancies detected:", fg=typer.colors.YELLOW)
        for key, count in sorted(totals.items()):
            typer.secho(f"  {key}: {count}", fg=typer.colors.YELLOW)
    else:
        typer.secho("All sources are consistent", fg=typer.colors.GREEN)

    if csv_report:
        _write_csv_report(csv_report, mismatches)
        typer.secho(f"Wrote CSV report to {csv_report}", fg=typer.colors.BLUE)
    if json_report:
        _write_json_report(json_report, mismatches)
        typer.secho(f"Wrote JSON report to {json_report}", fg=typer.colors.BLUE)

    if mismatches:
        raise typer.Exit(code=1)


__all__ = ["reconcile"]
