"""Preset management commands for the render submission CLI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import click
import structlog
import typer

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceIOError,
    OnePieceValidationError,
)

from .helpers import (
    DCC_CHOICES,
    FARM_CHOICES,
    refresh_capabilities_cache,
    resolve_priority_and_chunk_size,
)
from .submit_command import submit

log = structlog.get_logger(__name__)

PRESET_DIR_ENV = "ONEPIECE_RENDER_PRESET_DIR"
PRESET_DIR_DEFAULT = Path.home() / ".onepiece" / "render_presets"
PRESET_EXTENSION = ".json"


def _validate_preset_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise OnePieceValidationError("Preset name cannot be empty.")
    if any(sep in cleaned for sep in ("/", "\\")):
        raise OnePieceValidationError("Preset name cannot include path separators.")
    return cleaned


def _get_preset_dir() -> Path:
    override = os.environ.get(PRESET_DIR_ENV)
    if override:
        base = Path(override).expanduser().resolve()
    else:
        base = PRESET_DIR_DEFAULT
    base.mkdir(parents=True, exist_ok=True)
    return base


def _preset_path(name: str) -> Path:
    safe_name = _validate_preset_name(name)
    return _get_preset_dir() / f"{safe_name}{PRESET_EXTENSION}"


def _load_preset(name: str) -> dict[str, Any]:
    path = _preset_path(name)
    if not path.exists():
        raise OnePieceIOError(f"Preset '{name}' was not found at {path}.")
    return cast(dict[str, Any], json.loads(path.read_text()))


def _save_preset(name: str, data: dict[str, Any]) -> Path:
    path = _preset_path(name)
    serialised = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(serialised)
    return path


def _list_presets() -> list[tuple[str, dict[str, Any]]]:
    directory = _get_preset_dir()
    presets: list[tuple[str, dict[str, Any]]] = []
    for preset_file in sorted(directory.glob(f"*{PRESET_EXTENSION}")):
        name = preset_file.stem
        try:
            presets.append((name, json.loads(preset_file.read_text())))
        except json.JSONDecodeError:
            log.warning("render.presets.invalid", preset=str(preset_file))
    return presets


def list_presets() -> None:
    """List available render submission presets."""

    presets = _list_presets()
    if not presets:
        typer.secho("No render presets found.", fg=typer.colors.YELLOW)
        return

    for name, data in presets:
        farm = data.get("farm", "?")
        dcc = data.get("dcc", "?")
        frames = data.get("frames", "?")
        summary_parts = [f"farm={farm}"]
        if dcc != "?":
            summary_parts.append(f"dcc={dcc}")
        if frames != "?":
            summary_parts.append(f"frames={frames}")
        chunk = data.get("chunk_size")
        if chunk is not None:
            summary_parts.append(f"chunk={chunk}")
        typer.echo(f"{name}: {', '.join(summary_parts)}")


def save_preset(
    name: str = typer.Argument(..., help="Name used to identify the preset."),
    *,
    farm: str = typer.Option(
        ...,
        "--farm",
        help="Render farm targeted by this preset.",
        click_type=click.Choice(FARM_CHOICES, case_sensitive=False),
    ),
    dcc: str | None = typer.Option(
        None,
        "--dcc",
        help="DCC associated with the preset (defaults to prompting during use).",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    scene: Path | None = typer.Option(None, "--scene", help="Default scene file path."),
    frames: str | None = typer.Option(None, "--frames", help="Default frame range."),
    output: Path | None = typer.Option(
        None, "--output", help="Default output directory."
    ),
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
    resolved_dcc = dcc.lower() if dcc else None

    if refresh_capabilities:
        refresh_capabilities_cache(farm=farm)

    explicit_priority = priority is not None
    explicit_chunk = chunk_size is not None

    try:
        (
            resolved_priority,
            resolved_chunk,
            _,
            _,
        ) = resolve_priority_and_chunk_size(
            farm=farm,
            priority=priority,
            chunk_size=chunk_size,
            optimize=False,
        )
    except OnePieceExternalServiceError as exc:
        if explicit_priority or explicit_chunk:
            raise
        log.warning(
            "render.presets.capabilities_unavailable",
            farm=farm,
            error=str(exc),
        )
        resolved_priority = None
        resolved_chunk = None

    payload: dict[str, Any] = {"farm": farm}
    if resolved_priority is not None:
        payload["priority"] = resolved_priority
    if resolved_chunk is not None:
        payload["chunk_size"] = resolved_chunk
    if resolved_dcc:
        payload["dcc"] = resolved_dcc
    if scene:
        payload["scene"] = str(scene)
    if frames:
        payload["frames"] = frames
    if output:
        payload["output"] = str(output)
    if user:
        payload["user"] = user

    path = _save_preset(name, payload)
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

    preset = _load_preset(name)

    merged: dict[str, Any] = dict(preset)

    overrides: dict[str, Any] = {}
    if scene is not None:
        overrides["scene"] = str(scene)
    if frames is not None:
        overrides["frames"] = frames
    if output is not None:
        overrides["output"] = str(output)
    if farm is not None:
        overrides["farm"] = farm.lower()
    if dcc is not None:
        overrides["dcc"] = dcc.lower()
    if priority is not None:
        overrides["priority"] = priority
    if chunk_size is not None:
        overrides["chunk_size"] = chunk_size
    if user is not None:
        overrides["user"] = user

    merged.update(overrides)

    required_fields = {
        "farm": "--farm",
        "dcc": "--dcc",
        "scene": "--scene",
        "output": "--output",
    }
    missing = [hint for field, hint in required_fields.items() if not merged.get(field)]
    if missing:
        raise OnePieceValidationError(
            "Preset is missing required fields. Provide overrides for: "
            + ", ".join(missing)
        )

    typer.secho(f"Using preset '{name}'.", fg=typer.colors.BLUE)

    submit(
        dcc=str(merged["dcc"]),
        scene=Path(str(merged["scene"])),
        frames=str(merged.get("frames", frames or "1-100")),
        output=Path(str(merged["output"])),
        farm=str(merged["farm"]),
        priority=merged.get("priority"),
        chunk_size=merged.get("chunk_size"),
        user=merged.get("user"),
        refresh_capabilities=refresh_capabilities,
    )


__all__ = ["list_presets", "save_preset", "use_preset"]
