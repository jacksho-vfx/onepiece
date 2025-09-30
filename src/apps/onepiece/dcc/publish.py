"""CLI command for publishing packaged scene outputs."""

import json
from pathlib import Path
from typing import Literal, cast, Any

import structlog
import typer

from libraries.dcc.dcc_client import JSONValue, publish_scene
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
) -> None:
    """Package a scene and publish it to S3."""

    resolved_dcc = _resolve_dcc(dcc)
    resolved_show_type = _validate_show_type(show_type)
    metadata_dict = _load_metadata(metadata)

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
    )

    log.info("cli_publish_completed", package=str(package_path))
    typer.echo(f"Published package created at {package_path}")
