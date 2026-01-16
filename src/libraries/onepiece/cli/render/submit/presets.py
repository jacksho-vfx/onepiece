"""Preset management commands for the render submission CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import typer

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceIOError,
    OnePieceValidationError,
)

from ..presets import RenderPreset, RenderPresetStore
from .helpers import (
    DCC_CHOICES,
    FARM_CHOICES,
    refresh_capabilities_cache,
    validate_scene_and_output,
)
from .submit_command import submit


def _store() -> RenderPresetStore:
    return RenderPresetStore()


def _abort(message: str, *, code: int = 1) -> None:
    typer.secho(message, fg=typer.colors.RED)
    raise typer.Exit(code=code)


def list_presets() -> None:
    """List available render submission presets."""

    presets = _store().list()
    if not presets:
        typer.secho("No render presets found.", fg=typer.colors.YELLOW)
        return

    for record in presets:
        preset = record.preset
        summary_parts = [
            f"farm={preset.farm}",
            f"dcc={preset.dcc}",
            f"frames={preset.frames}",
            f"priority={preset.priority}",
        ]
        if preset.chunk_size is not None:
            summary_parts.append(f"chunk={preset.chunk_size}")
        if preset.user:
            summary_parts.append(f"user={preset.user}")
        location = record.path.parent
        typer.echo(
            f"{record.name} (v{preset.version}) [{location}]: {', '.join(summary_parts)}"
        )


def save_preset(
    name: str = typer.Argument(..., help="Name used to identify the preset."),
    *,
    farm: str = typer.Option(
        ...,
        "--farm",
        help="Render farm targeted by this preset.",
        click_type=click.Choice(FARM_CHOICES, case_sensitive=False),
    ),
    dcc: str = typer.Option(
        ...,
        "--dcc",
        help="DCC associated with the preset.",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    scene: Path = typer.Option(..., "--scene", help="Default scene file path."),
    frames: str = typer.Option(
        "1-100",
        "--frames",
        help="Frame range to render (e.g. 1-100 or 1-100x2).",
    ),
    output: Path = typer.Option(..., "--output", help="Default output directory."),
    priority: int | None = typer.Option(
        None,
        "--priority",
        help="Override the adapter priority default for this preset.",
    ),
    chunk_size: int | None = typer.Option(
        None,
        "--chunk-size",
        help="Override the adapter chunk size default for this preset.",
    ),
    user: str | None = typer.Option(None, "--user", help="Default submitting user."),
    refresh_capabilities: bool = typer.Option(
        False,
        "--refresh-capabilities",
        help="Reload farm capabilities before validating the preset.",
    ),
) -> None:
    """Persist a render submission preset to disk."""

    farm = farm.lower()
    dcc = dcc.lower()
    if refresh_capabilities:
        refresh_capabilities_cache(farm=farm)

    store = _store()
    try:
        preset = RenderPreset.from_mapping(
            name,
            {
                "farm": farm,
                "dcc": dcc,
                "scene": str(scene),
                "frames": frames,
                "output": str(output),
                "priority": priority,
                "chunk_size": chunk_size,
                "user": user,
            },
            capability_provider=store.capability_provider,
        )
    except (OnePieceValidationError, OnePieceExternalServiceError) as exc:
        _abort(str(exc))
    path = store.save(preset)
    typer.secho(f"Saved preset '{name}' to {path}.", fg=typer.colors.GREEN)


def use_preset(
    name: str = typer.Argument(..., help="Name of the preset to execute."),
    *,
    scene: Path | None = typer.Option(None, "--scene", help="Override the scene file."),
    frames: str | None = typer.Option(
        None, "--frames", help="Override the frame range."
    ),
    output: Path | None = typer.Option(
        None, "--output", help="Override the output directory."
    ),
    farm: str | None = typer.Option(
        None,
        "--farm",
        help="Override the preset farm.",
        click_type=click.Choice(FARM_CHOICES, case_sensitive=False),
    ),
    dcc: str | None = typer.Option(
        None,
        "--dcc",
        help="Override the preset DCC.",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    priority: int | None = typer.Option(
        None, "--priority", help="Override the preset priority."
    ),
    chunk_size: int | None = typer.Option(
        None, "--chunk-size", help="Override the preset chunk size."
    ),
    user: str | None = typer.Option(
        None, "--user", help="Override the submitting user."
    ),
    refresh_capabilities: bool = typer.Option(
        False,
        "--refresh-capabilities",
        help="Reload farm capabilities before executing the preset.",
    ),
) -> None:
    """Execute a preset, optionally overriding fields before submission."""

    store = _store()
    try:
        record = store.load(name)
    except (OnePieceIOError, OnePieceValidationError) as exc:
        _abort(str(exc))

    merged: dict[str, Any] = record.preset.serialise()
    if scene is not None:
        merged["scene"] = str(scene)
    if frames is not None:
        merged["frames"] = frames
    if output is not None:
        merged["output"] = str(output)
    if farm is not None:
        merged["farm"] = farm.lower()
    if dcc is not None:
        merged["dcc"] = dcc.lower()
    if priority is not None:
        merged["priority"] = priority
    if chunk_size is not None:
        merged["chunk_size"] = chunk_size
    if user is not None:
        merged["user"] = user

    effective_farm = str(merged.get("farm", record.preset.farm))
    if refresh_capabilities:
        refresh_capabilities_cache(farm=effective_farm)

    try:
        preset = RenderPreset.from_mapping(
            name,
            merged,
            capability_provider=store.capability_provider,
        )
    except (OnePieceValidationError, OnePieceExternalServiceError) as exc:
        _abort(str(exc))

    try:
        validate_scene_and_output(preset.scene, preset.output)
    except OnePieceValidationError as exc:
        _abort(str(exc))

    typer.secho(f"Using preset '{name}'.", fg=typer.colors.BLUE)

    submit(
        dcc=preset.dcc,
        scene=preset.scene,
        frames=preset.frames,
        output=preset.output,
        farm=preset.farm,
        priority=preset.priority,
        chunk_size=preset.chunk_size,
        user=preset.user,
        refresh_capabilities=False,
    )


def export_preset(
    name: str = typer.Argument(..., help="Name of the preset to export."),
    destination: Path = typer.Argument(
        ..., help="File or directory where the preset should be written."
    ),
) -> None:
    """Write a preset to a portable JSON file."""

    store = _store()
    target = store.export(name, destination)
    typer.secho(f"Exported preset '{name}' to {target}.", fg=typer.colors.GREEN)


def import_preset(
    path: Path = typer.Argument(..., help="Path to a JSON preset file."),
    name: str | None = typer.Option(
        None, "--name", help="Override the name stored for the imported preset."
    ),
) -> None:
    """Import a preset JSON file into the local preset store."""

    store = _store()
    record = store.import_file(path, name=name)
    typer.secho(
        f"Imported preset '{record.name}' into {record.path}", fg=typer.colors.GREEN
    )


__all__ = [
    "export_preset",
    "import_preset",
    "list_presets",
    "save_preset",
    "use_preset",
]
