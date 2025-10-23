"""CLI helpers for persisting and applying ShotGrid hierarchy templates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
import typer

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceIOError,
    OnePieceValidationError,
)
from libraries.integrations.shotgrid.client import ShotgridClient, ShotgridOperationError

from ._inputs import load_structured_mapping

log = structlog.get_logger(__name__)

app = typer.Typer(help="Shotgrid hierarchy template utilities.")


def _dump_summary(summary: dict[str, Any]) -> None:
    typer.echo(json.dumps(summary, indent=2, sort_keys=True))


def _load_context(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    context = load_structured_mapping(path)
    return dict(context)


@app.command("save-template")
def save_template_command(
    input_path: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON/YAML file describing the hierarchy template to persist.",
    ),
    output_path: Path = typer.Option(
        ...,
        "--output",
        "-o",
        dir_okay=False,
        writable=True,
        help=(
            "Where the normalized template should be written. File extension "
            "determines JSON or YAML output."
        ),
    ),
) -> None:
    """Validate and persist a hierarchy template definition."""

    client = ShotgridClient()

    try:
        template_payload = load_structured_mapping(input_path)
        template = client.deserialize_hierarchy_template(template_payload)
    except OnePieceIOError:
        raise
    except OnePieceValidationError:
        raise
    except ValueError as exc:
        log.error(
            "shotgrid.templates.deserialize_failed",
            input=str(input_path),
            error=str(exc),
        )
        raise OnePieceValidationError(str(exc)) from exc

    try:
        client.save_hierarchy_template(template, output_path)
    except OSError as exc:  # noqa: BLE001 - surfaced to CLI
        log.error(
            "shotgrid.templates.save_failed",
            output=str(output_path),
            error=str(exc),
        )
        raise OnePieceIOError(
            f"Failed to write hierarchy template to '{output_path}': {exc}"
        ) from exc

    log.info(
        "shotgrid.templates.save_success",
        template=template.name,
        output=str(output_path),
    )
    _dump_summary({"template": template.name, "output": str(output_path)})


@app.command("load-template")
def load_template_command(
    input_path: Path = typer.Option(
        ...,
        "--input",
        "-i",
        exists=True,
        dir_okay=False,
        readable=True,
        help="JSON/YAML file containing a hierarchy template.",
    ),
    project: str = typer.Option(
        ...,
        "--project",
        "-p",
        help="Name of the ShotGrid project where the template should be applied.",
    ),
    context_path: Path | None = typer.Option(
        None,
        "--context",
        "-c",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional JSON/YAML file with key/value context merged into nodes.",
    ),
) -> None:
    """Load a hierarchy template and apply it to a ShotGrid project."""

    client = ShotgridClient()

    try:
        template = client.load_hierarchy_template(input_path)
    except OSError as exc:  # noqa: BLE001 - surfaced to CLI
        log.error(
            "shotgrid.templates.load_failed",
            input=str(input_path),
            error=str(exc),
        )
        raise OnePieceIOError(
            f"Failed to read hierarchy template from '{input_path}': {exc}"
        ) from exc
    except ValueError as exc:
        log.error(
            "shotgrid.templates.parse_failed",
            input=str(input_path),
            error=str(exc),
        )
        raise OnePieceValidationError(str(exc)) from exc

    context = _load_context(context_path)

    try:
        created = client.apply_hierarchy_template(project, template, context=context)
    except ShotgridOperationError as exc:
        log.error(
            "shotgrid.templates.apply_failed",
            project=project,
            template=template.name,
            error=str(exc),
        )
        raise OnePieceExternalServiceError(
            f"Failed to apply hierarchy template '{template.name}': {exc}"
        ) from exc

    summary = {
        "project": project,
        "template": template.name,
        "created": {entity: len(records) for entity, records in created.items()},
    }
    log.info(
        "shotgrid.templates.apply_success",
        project=project,
        template=template.name,
        entities=list(summary["created"].keys()),
    )
    _dump_summary(summary)
