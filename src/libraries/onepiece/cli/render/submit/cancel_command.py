"""Render cancellation command implementation."""

from __future__ import annotations

import structlog
import typer

from apps.onepiece.utils.errors import (
    OnePieceConfigError,
    OnePieceExternalServiceError,
    OnePieceValidationError,
)

from .helpers import RenderCliModuleResolver, coerce_text

_resolver = RenderCliModuleResolver()
log = _resolver.resolve_logger(structlog.get_logger(__name__))


def cancel_render_job(
    job_id: str = typer.Argument(..., help="Identifier returned by the render farm."),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Configuration profile providing Trafalgar render settings.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Ignore cancellation unsupported warnings returned by the adapter.",
    ),
) -> None:
    """Request cancellation of an in-flight render job via Trafalgar."""

    logger = _resolver.resolve_logger(log)
    from ..jobs import RenderJobClient as DefaultClient
    from ..jobs import RenderJobClientError as DefaultError

    error_class = _resolver.resolve_attribute("RenderJobClientError", DefaultError)

    logger.info(
        "render.cancel.start",
        job_id=job_id,
        profile=profile,
        force=force,
    )

    try:
        client_class = _resolver.resolve_attribute("RenderJobClient", DefaultClient)
        client = client_class(profile=profile)
    except OnePieceConfigError as exc:
        raise OnePieceValidationError(str(exc)) from exc
    except error_class as exc:
        logger.error(
            "render.cancel.client_error",
            job_id=job_id,
            error=str(exc),
            code=exc.code,
            status=exc.status_code,
        )
        raise OnePieceExternalServiceError(str(exc)) from exc

    with client:
        try:
            result = client.cancel_job(job_id)
        except error_class as exc:
            if exc.code == "render.cancellation_unsupported" and force:
                logger.warning(
                    "render.cancel.unsupported",
                    job_id=job_id,
                    code=exc.code,
                    hint=exc.hint,
                    status=exc.status_code,
                    force=True,
                )
                message = (
                    exc.message or "Render farm does not support job cancellation."
                )
                typer.secho(
                    f"{message} (ignored due to --force).",
                    fg=typer.colors.YELLOW,
                )
                if exc.hint:
                    typer.secho(f"Hint: {exc.hint}", fg=typer.colors.YELLOW)
                return

            logger.error(
                "render.cancel.failed",
                job_id=job_id,
                code=exc.code,
                status=exc.status_code,
                hint=exc.hint,
                force=force,
            )
            error_message = f"Render cancellation failed: {exc.message}"
            if exc.hint:
                error_message = f"{error_message} Hint: {exc.hint}"
            raise OnePieceExternalServiceError(error_message) from exc

    job_label = coerce_text(result.get("job_id") or job_id)
    status = coerce_text(result.get("status")) or "<unknown>"
    farm_type = coerce_text(result.get("farm_type")) or "<unknown>"
    message = result.get("message")
    logger.info(
        "render.cancel.success",
        job_id=job_label,
        status=status,
        farm_type=farm_type,
        message=message if isinstance(message, str) else None,
    )

    typer.secho(
        f"Cancellation status for {job_label}: {status}",
        fg=typer.colors.GREEN,
    )
    if farm_type:
        typer.echo(f"Adapter: {farm_type}")
    if isinstance(message, str) and message.strip():
        typer.secho(f"Message: {message.strip()}", fg=typer.colors.GREEN)


__all__ = ["cancel_render_job"]
