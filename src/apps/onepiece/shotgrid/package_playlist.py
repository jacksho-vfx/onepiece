"""CLI helpers for ShotGrid playlist deliveries and bulk utilities."""

import json
from enum import Enum
from pathlib import Path
from typing import Any, cast

import structlog
import typer

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceIOError,
    OnePieceValidationError,
)
from ._inputs import load_structured_array
from libraries.integrations.shotgrid.client import ShotgridClient, ShotgridOperationError
from libraries.integrations.shotgrid.playlist_delivery import (
    Recipient,
    package_playlist_for_mediashuttle,
)

log = structlog.get_logger(__name__)

app = typer.Typer(help="Shotgrid related commands.")


class BulkOperation(str, Enum):
    """Supported bulk operations."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


def _load_entity_payloads(path: Path, entity_label: str) -> list[dict[str, Any]]:
    data = load_structured_array(path)
    payloads: list[dict[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise OnePieceValidationError(
                f"{entity_label} payload at index {index} must be a JSON object."
            )
        payloads.append(item)
    return payloads


def _resolve_entity_ids(
    ids: list[int] | None, input_path: Path | None, entity_label: str
) -> list[int]:
    if ids:
        return [int(entity_id) for entity_id in ids]

    if input_path is None:
        raise OnePieceValidationError(
            f"Provide either --id or --input when deleting {entity_label.lower()}s."
        )

    resolved: list[int] = []
    for index, item in enumerate(load_structured_array(input_path)):
        try:
            resolved.append(int(item))
        except (TypeError, ValueError) as exc:
            raise OnePieceValidationError(
                f"{entity_label} id at index {index} must be an integer."
            ) from exc
    return resolved


def _require_input(
    operation: BulkOperation, input_path: Path | None, label: str
) -> Path:
    if input_path is None:
        raise OnePieceValidationError(
            f"--input is required when running '{operation.value}' for {label}."
        )
    return input_path


def _dump_summary(summary: dict[str, Any]) -> None:
    typer.echo(json.dumps(summary, indent=2, sort_keys=True))


@app.command("package-playlist")
def package_playlist_command(
    project: str = typer.Option(..., "--project", "-p", help="ShotGrid project name"),
    playlist: str = typer.Option(
        ..., "--playlist", "-l", help="ShotGrid playlist name"
    ),
    destination: Path = typer.Option(
        Path.cwd(),
        "--destination",
        "-d",
        file_okay=False,
        help="Directory where the MediaShuttle package will be created.",
    ),
    recipient: str = typer.Option(
        "client",
        "--recipient",
        "-r",
        help="Recipient for the package: 'client' or 'vendor'.",
        case_sensitive=False,
    ),
) -> None:
    """Package the media referenced by a ShotGrid playlist."""

    normalized_recipient = recipient.lower()
    if normalized_recipient not in {"client", "vendor"}:
        raise OnePieceValidationError("Recipient must be either 'client' or 'vendor'.")

    sg_client = ShotgridClient()
    package_destination = destination.expanduser()

    try:
        summary = package_playlist_for_mediashuttle(
            sg_client,
            project_name=project,
            playlist_name=playlist,
            destination=package_destination,
            recipient=cast(Recipient, normalized_recipient),
        )
    except OSError as exc:  # noqa: BLE001 - surfaced to the CLI.
        log.error(
            "package_playlist.failed",
            project=project,
            playlist=playlist,
            error=str(exc),
        )
        raise OnePieceIOError(
            f"Failed to write package data to {package_destination}: {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced to the CLI.
        log.error(
            "package_playlist.failed",
            project=project,
            playlist=playlist,
            error=str(exc),
        )
        raise OnePieceExternalServiceError(
            f"Failed to package playlist '{playlist}' for project '{project}': {exc}"
        ) from exc

    log.info(
        "package_playlist.success",
        project=project,
        playlist=playlist,
        package=str(summary.package_path),
    )
    typer.echo(f"Package created at {summary.package_path}")


@app.command("bulk-playlists")
def bulk_playlists_command(
    operation: BulkOperation = typer.Argument(
        ..., help="Bulk operation to run: create, update, or delete."
    ),
    input_path: Path | None = typer.Option(
        None,
        "--input",
        "-i",
        exists=True,
        dir_okay=False,
        file_okay=True,
        readable=True,
        help="JSON file describing playlist payloads or IDs.",
    ),
    playlist_ids: list[int] | None = typer.Option(
        None,
        "--id",
        "-d",
        help=("Playlist IDs to delete. Repeat the option to supply multiple IDs."),
        show_default=False,
    ),
) -> None:
    """Run bulk create/update/delete operations for ShotGrid playlists."""

    sg_client = ShotgridClient()
    entity_label = "Playlist"

    if operation is BulkOperation.DELETE:
        playlist_id_list = _resolve_entity_ids(playlist_ids, input_path, entity_label)
        requested = len(playlist_id_list)
        try:
            sg_client.bulk_delete_entities("Playlist", playlist_id_list)
        except ShotgridOperationError as exc:
            log.error(
                "shotgrid.bulk.delete_failed",
                entity=entity_label,
                operation=operation.value,
                error=str(exc),
            )
            raise OnePieceExternalServiceError(
                f"Failed to delete {entity_label.lower()}s: {exc}"
            ) from exc

        log.info(
            "shotgrid.bulk.delete_success",
            entity=entity_label,
            requested=requested,
        )
        _dump_summary(
            {
                "entity": entity_label,
                "operation": operation.value,
                "requested": requested,
                "succeeded": requested,
                "failed": 0,
                "ids": playlist_id_list,
            }
        )
        return

    payload_path = _require_input(operation, input_path, f"{entity_label.lower()}s")
    payloads = _load_entity_payloads(payload_path, entity_label)

    try:
        if operation is BulkOperation.CREATE:
            result = sg_client.bulk_create_entities("Playlist", payloads)
        else:
            result = sg_client.bulk_update_entities("Playlist", payloads)
    except ValueError as exc:
        log.error(
            "shotgrid.bulk.invalid_payload",
            entity=entity_label,
            operation=operation.value,
            error=str(exc),
        )
        raise OnePieceValidationError(str(exc)) from exc
    except ShotgridOperationError as exc:
        log.error(
            "shotgrid.bulk.operation_failed",
            entity=entity_label,
            operation=operation.value,
            error=str(exc),
        )
        raise OnePieceExternalServiceError(
            f"Failed to {operation.value} {entity_label.lower()}s: {exc}"
        ) from exc

    requested = len(payloads)
    succeeded = len(result)
    ids = [payload.get("id") for payload in result if isinstance(payload, dict)]

    log.info(
        "shotgrid.bulk.operation_success",
        entity=entity_label,
        operation=operation.value,
        requested=requested,
        succeeded=succeeded,
    )

    _dump_summary(
        {
            "entity": entity_label,
            "operation": operation.value,
            "requested": requested,
            "succeeded": succeeded,
            "failed": requested - succeeded,
            "ids": [entity_id for entity_id in ids if entity_id is not None],
        }
    )


@app.command("bulk-versions")
def bulk_versions_command(
    operation: BulkOperation = typer.Argument(
        ..., help="Bulk operation to run: create, update, or delete."
    ),
    input_path: Path | None = typer.Option(
        None,
        "--input",
        "-i",
        exists=True,
        dir_okay=False,
        file_okay=True,
        readable=True,
        help="JSON file describing version payloads or IDs.",
    ),
    version_ids: list[int] | None = typer.Option(
        None,
        "--id",
        "-d",
        help=("Version IDs to delete. Repeat the option to supply multiple IDs."),
        show_default=False,
    ),
) -> None:
    """Run bulk create/update/delete operations for ShotGrid versions."""

    sg_client = ShotgridClient()
    entity_label = "Version"

    if operation is BulkOperation.DELETE:
        version_id_list = _resolve_entity_ids(version_ids, input_path, entity_label)
        requested = len(version_id_list)
        try:
            sg_client.bulk_delete_entities("Version", version_id_list)
        except ShotgridOperationError as exc:
            log.error(
                "shotgrid.bulk.delete_failed",
                entity=entity_label,
                operation=operation.value,
                error=str(exc),
            )
            raise OnePieceExternalServiceError(
                f"Failed to delete {entity_label.lower()}s: {exc}"
            ) from exc

        log.info(
            "shotgrid.bulk.delete_success",
            entity=entity_label,
            requested=requested,
        )
        _dump_summary(
            {
                "entity": entity_label,
                "operation": operation.value,
                "requested": requested,
                "succeeded": requested,
                "failed": 0,
                "ids": version_id_list,
            }
        )
        return

    payload_path = _require_input(operation, input_path, f"{entity_label.lower()}s")
    payloads = _load_entity_payloads(payload_path, entity_label)

    try:
        if operation is BulkOperation.CREATE:
            result = sg_client.bulk_create_entities("Version", payloads)
        else:
            result = sg_client.bulk_update_entities("Version", payloads)
    except ValueError as exc:
        log.error(
            "shotgrid.bulk.invalid_payload",
            entity=entity_label,
            operation=operation.value,
            error=str(exc),
        )
        raise OnePieceValidationError(str(exc)) from exc
    except ShotgridOperationError as exc:
        log.error(
            "shotgrid.bulk.operation_failed",
            entity=entity_label,
            operation=operation.value,
            error=str(exc),
        )
        raise OnePieceExternalServiceError(
            f"Failed to {operation.value} {entity_label.lower()}s: {exc}"
        ) from exc

    requested = len(payloads)
    succeeded = len(result)
    ids = [payload.get("id") for payload in result if isinstance(payload, dict)]

    log.info(
        "shotgrid.bulk.operation_success",
        entity=entity_label,
        operation=operation.value,
        requested=requested,
        succeeded=succeeded,
    )

    _dump_summary(
        {
            "entity": entity_label,
            "operation": operation.value,
            "requested": requested,
            "succeeded": succeeded,
            "failed": requested - succeeded,
            "ids": [entity_id for entity_id in ids if entity_id is not None],
        }
    )
