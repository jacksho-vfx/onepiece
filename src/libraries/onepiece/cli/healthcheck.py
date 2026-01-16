"""Healthcheck command group for verifying CLI prerequisites."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import structlog
import typer
from boto3 import Session
from botocore.exceptions import BotoCoreError, NoCredentialsError, ProfileNotFound
from pydantic import ValidationError

from apps.onepiece.config import ProfileContext, load_profile
from apps.onepiece.utils.errors import OnePieceConfigError
from libraries.integrations.shotgrid.config import load_config as load_shotgrid_config

from .misc.info import mask_sensitive_value

log = structlog.get_logger(__name__)
app = typer.Typer(name="healthcheck", help="Validate environment prerequisites")


@dataclass(frozen=True)
class HealthProbeResult:
    """Outcome of an individual health probe."""

    name: str
    ok: bool
    summary: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "details": dict(self.details),
        }


def probe_profile(
    *, profile: str | None, workspace: Path | None, project_root: Path | None
) -> HealthProbeResult:
    """Verify the OnePiece configuration profile can be resolved."""

    try:
        context = load_profile(
            profile=profile, workspace=workspace, project_root=project_root
        )
    except OnePieceConfigError as exc:
        return HealthProbeResult(
            name="config", ok=False, summary=str(exc), details={"profile": profile}
        )

    return HealthProbeResult(
        name="config",
        ok=True,
        summary=f"Loaded profile '{context.name}'",
        details=_profile_details(context),
    )


def _profile_details(context: ProfileContext) -> dict[str, Any]:
    return {
        "profile": context.name,
        "pipelines": sorted(context.pipelines),
        "sources": [str(path) for path in context.sources],
    }


def probe_shotgrid() -> HealthProbeResult:
    """Confirm ShotGrid settings are present and valid."""

    try:
        settings = load_shotgrid_config()
    except ValidationError as exc:
        return HealthProbeResult(
            name="shotgrid",
            ok=False,
            summary="Invalid ShotGrid configuration",
            details={"errors": exc.errors()},
        )

    return HealthProbeResult(
        name="shotgrid",
        ok=True,
        summary="ShotGrid configuration loaded",
        details={
            "base_url": settings.base_url,
            "script_name": settings.script_name,
            "api_key": mask_sensitive_value(settings.api_key),
        },
    )


def probe_aws(profile: str | None) -> HealthProbeResult:
    """Validate AWS credentials can be resolved for the chosen profile."""

    try:
        session = Session(profile_name=profile)
    except ProfileNotFound as exc:
        return HealthProbeResult(
            name="aws",
            ok=False,
            summary=str(exc),
            details={"profile": profile},
        )

    try:
        credentials = session.get_credentials()
    except (BotoCoreError, NoCredentialsError) as exc:
        return HealthProbeResult(
            name="aws",
            ok=False,
            summary=f"Failed to resolve AWS credentials: {exc}",
            details={"profile": profile},
        )

    if credentials is None:
        return HealthProbeResult(
            name="aws",
            ok=False,
            summary="No AWS credentials found",
            details={"profile": profile},
        )

    frozen = credentials.get_frozen_credentials()
    masked_key = mask_sensitive_value(frozen.access_key)

    return HealthProbeResult(
        name="aws",
        ok=True,
        summary="AWS credentials resolved",
        details={
            "profile": profile or "default",
            "access_key": masked_key,
            "token_present": bool(frozen.token),
        },
    )


def _render_text(results: list[HealthProbeResult]) -> None:
    typer.echo("=== OnePiece Healthcheck ===")
    for result in results:
        status = "ok" if result.ok else "failed"
        color = typer.colors.GREEN if result.ok else typer.colors.RED
        typer.secho(f"[{status}] {result.name}: {result.summary}", fg=color)
        for key, value in result.details.items():
            typer.echo(f"  - {key}: {value}")


@app.command("run")
def run(
    output_format: str = typer.Option(
        "text",
        "--format",
        "-f",
        help="Choose output format (text or json).",
        case_sensitive=False,
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Override the profile name to load for configuration validation.",
    ),
    workspace: Path | None = typer.Option(
        None,
        "--workspace",
        dir_okay=True,
        file_okay=False,
        resolve_path=True,
        help="Path to a workspace directory that may contain onepiece.toml.",
    ),
    project_root: Path | None = typer.Option(
        None,
        "--project-root",
        dir_okay=True,
        file_okay=False,
        resolve_path=True,
        help="Project root used to discover configuration files.",
    ),
    aws_profile: str | None = typer.Option(
        None,
        "--aws-profile",
        "-a",
        help="AWS profile name to resolve credentials for (defaults to environment)",
    ),
) -> None:
    """Run environment health checks and report the results."""

    results = [
        probe_profile(profile=profile, workspace=workspace, project_root=project_root),
        probe_shotgrid(),
        probe_aws(aws_profile),
    ]

    ok = all(result.ok for result in results)
    payload = {"ok": ok, "probes": [result.to_dict() for result in results]}

    log.info(
        "healthcheck",
        ok=ok,
        failed=[result.name for result in results if not result.ok],
        probes=payload["probes"],
    )

    if output_format.lower() == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _render_text(results)

    if not ok:
        raise typer.Exit(code=1)
