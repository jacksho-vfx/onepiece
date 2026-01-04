"""Render status command implementation."""

from __future__ import annotations

import json

import typer

from apps.onepiece.utils.errors import (
    OnePieceConfigError,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)

from .helpers import RenderCliModuleResolver, extract_history


_resolver = RenderCliModuleResolver()


def render_status(
    job_id: str = typer.Argument(..., help="Identifier returned by the render farm."),
    farm: str | None = typer.Option(
        None,
        "--farm",
        help="Optional farm filter when job identifiers overlap between adapters.",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Configuration profile providing Trafalgar render settings.",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        help="Output the raw JSON payload for scripting integrations.",
    ),
) -> None:
    """Fetch render job metadata from the Trafalgar render API."""

    from ..jobs import (
        RenderJobClient as DefaultClient,
        RenderJobClientError as DefaultError,
    )

    client_class = _resolver.resolve_attribute("RenderJobClient", DefaultClient)
    error_class = _resolver.resolve_attribute("RenderJobClientError", DefaultError)

    try:
        client = client_class(profile=profile)
    except OnePieceConfigError as exc:
        raise OnePieceValidationError(str(exc)) from exc
    except error_class as exc:
        raise OnePieceExternalServiceError(str(exc)) from exc

    with client:
        try:
            job = client.get_job(job_id, farm=farm)
        except error_class as exc:
            if exc.status_code == 404:
                raise OnePieceExternalServiceError(
                    f"Render job '{job_id}' was not found."
                ) from exc
            raise OnePieceExternalServiceError(str(exc)) from exc

    if raw:
        typer.echo(json.dumps(job, indent=2, sort_keys=True))
        return

    typer.secho(f"Render job {job.get('job_id', job_id)}", fg=typer.colors.CYAN)
    farm_value = job.get("farm") or farm or "<unknown>"
    farm_type = job.get("farm_type") or "<unknown>"
    typer.echo(f"Farm: {farm_value} ({farm_type})")
    typer.echo(f"Status: {job.get('status', '<unknown>')}")
    message = job.get("message")
    if isinstance(message, str) and message:
        typer.echo(f"Message: {message}")

    history = extract_history(job)
    if history:
        typer.echo("History:")
        for entry in history:
            typer.echo(f"  - {entry}")
    else:
        typer.echo("History: <not available>")


__all__ = ["render_status"]
