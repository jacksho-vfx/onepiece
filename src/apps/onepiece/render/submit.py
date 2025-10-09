"""Render submission CLI command with preset helpers."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
from typing import Any, Final, cast

import click
import structlog
import typer

from libraries.render import deadline, mock, opencue, tractor
from libraries.render.base import (
    AdapterCapabilities,
    RenderAdapterNotImplementedError,
    RenderSubmissionError,
)
from libraries.render.models import CapabilityProvider, RenderAdapter

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceIOError,
    OnePieceRuntimeError,
    OnePieceValidationError,
)

log = structlog.get_logger(__name__)

app = typer.Typer(name="render", help="Render farm submission commands.")
presets_app = typer.Typer(name="preset", help="Manage render submission presets.")
app.add_typer(presets_app, name="preset")

DCC_CHOICES: Final[tuple[str, ...]] = ("maya", "nuke", "houdini", "blender", "max")
FARM_CHOICES: Final[tuple[str, ...]] = ("deadline", "tractor", "opencue", "mock")

PRESET_DIR_ENV: Final[str] = "ONEPIECE_RENDER_PRESET_DIR"
PRESET_DIR_DEFAULT: Final[Path] = Path.home() / ".onepiece" / "render_presets"
PRESET_EXTENSION: Final[str] = ".json"

FARM_ADAPTERS: Final[dict[str, RenderAdapter]] = {
    "deadline": deadline.submit_job,
    "tractor": tractor.submit_job,
    "opencue": opencue.submit_job,
    "mock": mock.submit_job,
}

FARM_CAPABILITY_PROVIDERS: Final[dict[str, CapabilityProvider]] = {
    "deadline": deadline.get_capabilities,
    "tractor": tractor.get_capabilities,
    "opencue": opencue.get_capabilities,
    "mock": mock.get_capabilities,
}


def _get_adapter(farm: str) -> RenderAdapter:
    adapter = FARM_ADAPTERS.get(farm)
    if adapter is None:
        raise OnePieceValidationError(f"Unknown render farm '{farm}'.")
    return adapter


def _get_adapter_capabilities(farm: str) -> AdapterCapabilities:
    provider = FARM_CAPABILITY_PROVIDERS.get(farm)
    if provider is None:
        raise OnePieceValidationError(f"Unknown render farm '{farm}'.")
    try:
        return provider()
    except RenderSubmissionError as exc:
        raise OnePieceExternalServiceError(
            f"Failed to query capabilities from '{farm}' adapter: {exc}"
        ) from exc


def _resolve_priority_and_chunk_size(
    *,
    farm: str,
    priority: int | None,
    chunk_size: int | None,
    capabilities: AdapterCapabilities | None = None,
    capability_provider: CapabilityProvider | None = None,
) -> tuple[int, int | None, AdapterCapabilities]:
    resolved_capabilities: AdapterCapabilities
    if capabilities is not None:
        resolved_capabilities = dict(capabilities)
    else:
        provider = capability_provider
        if provider is None:
            resolved_capabilities = _get_adapter_capabilities(farm)
        else:
            try:
                resolved_capabilities = provider() or {}
            except RenderSubmissionError as exc:
                raise OnePieceExternalServiceError(
                    f"Failed to query capabilities from '{farm}' adapter: {exc}"
                ) from exc

    resolved_priority = priority
    if resolved_priority is None:
        resolved_priority = resolved_capabilities.get("default_priority", 50)

    min_priority = resolved_capabilities.get("priority_min")
    max_priority = resolved_capabilities.get("priority_max")
    if min_priority is not None and resolved_priority < min_priority:
        raise OnePieceValidationError(
            f"Priority {resolved_priority} is below the supported minimum of {min_priority} (--priority)."
        )
    if max_priority is not None and resolved_priority > max_priority:
        raise OnePieceValidationError(
            f"Priority {resolved_priority} exceeds the supported maximum of {max_priority} (--priority)."
        )

    chunk_enabled = resolved_capabilities.get("chunk_size_enabled", False)
    resolved_chunk = (
        chunk_size
        if chunk_size is not None
        else resolved_capabilities.get("default_chunk_size")
    )

    if resolved_chunk is not None:
        if not chunk_enabled:
            raise OnePieceValidationError(
                "Chunk sizing is not supported by this adapter (--chunk-size)."
            )
        min_chunk = resolved_capabilities.get("chunk_size_min")
        max_chunk = resolved_capabilities.get("chunk_size_max")
        if min_chunk is not None and resolved_chunk < min_chunk:
            raise OnePieceValidationError(
                f"Chunk size {resolved_chunk} is below the supported minimum of {min_chunk} (--chunk-size)."
            )
        if max_chunk is not None and resolved_chunk > max_chunk:
            raise OnePieceValidationError(
                f"Chunk size {resolved_chunk} exceeds the supported maximum of {max_chunk} (--chunk-size)."
            )
    elif chunk_size is not None:
        # Explicitly requested None but the adapter does not support chunking.
        raise OnePieceValidationError(
            "Chunk sizing is not supported by this adapter (--chunk-size)."
        )

    return resolved_priority, resolved_chunk, resolved_capabilities


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


@app.command("submit")
def submit(
    *,
    dcc: str = typer.Option(
        ...,
        "--dcc",
        help="Which DCC generated the render.",
        click_type=click.Choice(DCC_CHOICES, case_sensitive=False),
    ),
    scene: Path = typer.Option(
        ..., "--scene", help="Path to the scene file to render."
    ),
    frames: str = typer.Option(
        "1-100",
        "--frames",
        help="Frame range to render (e.g. 1-100 or 1-100x2).",
    ),
    output: Path = typer.Option(..., "--output", help="Directory for rendered frames."),
    farm: str = typer.Option(
        "mock",
        "--farm",
        help="Render farm manager to submit to.",
        click_type=click.Choice(FARM_CHOICES, case_sensitive=False),
    ),
    priority: int | None = typer.Option(
        None,
        "--priority",
        help="Render job priority (falls back to the adapter default).",
    ),
    chunk_size: int | None = typer.Option(
        None,
        "--chunk-size",
        help="Frames per chunk to dispatch when supported by the adapter.",
    ),
    user: str | None = typer.Option(
        None,
        "--user",
        help="Submitting user (defaults to the current system user).",
    ),
) -> None:
    """Submit a render job to the configured farm."""

    resolved_user = user or getpass.getuser()
    farm = farm.lower()
    dcc = dcc.lower()

    if not scene.exists():
        raise OnePieceValidationError(
            f"Scene file '{scene}' does not exist (--scene)."
        )
    if not scene.is_file():
        raise OnePieceValidationError(
            f"Scene path '{scene}' is not a file (--scene)."
        )

    if not output.exists():
        raise OnePieceValidationError(
            f"Output directory '{output}' does not exist (--output)."
        )
    if not output.is_dir():
        raise OnePieceValidationError(
            f"Output path '{output}' is not a directory (--output)."
        )

    resolved_priority, resolved_chunk, capabilities = _resolve_priority_and_chunk_size(
        farm=farm,
        priority=priority,
        chunk_size=chunk_size,
    )

    log.info(
        "render.submit.start",
        dcc=dcc,
        scene=str(scene),
        frames=frames,
        output=str(output),
        farm=farm,
        priority=resolved_priority,
        chunk_size=resolved_chunk,
        user=resolved_user,
        capabilities=capabilities,
    )

    adapter: RenderAdapter = _get_adapter(farm)

    try:
        result = adapter(
            scene=str(scene),
            frames=frames,
            output=str(output),
            dcc=dcc,
            priority=resolved_priority,
            user=resolved_user,
            chunk_size=resolved_chunk,
        )
    except RenderAdapterNotImplementedError as exc:
        log.warning(
            "render.submit.not_implemented",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
            hint=exc.hint,
        )
        typer.secho(
            f"Render adapter response: {exc}",
            fg=typer.colors.YELLOW,
        )
        if exc.hint:
            typer.secho(exc.hint, fg=typer.colors.YELLOW)
        return
    except RenderSubmissionError as exc:
        log.error(
            "render.submit.failed",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
            error=str(exc),
        )
        raise OnePieceExternalServiceError(f"Render submission failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive programming
        log.exception(
            "render.submit.error",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
        )
        raise OnePieceRuntimeError(
            "Render submission failed due to an unexpected error."
        ) from exc

    job_id = result.get("job_id", "")
    status = result.get("status", "unknown")
    farm_type = result.get("farm_type", farm)

    message = result.get("message")

    log.info(
        "render.submit.success",
        dcc=dcc,
        farm=farm_type,
        scene=str(scene),
        frames=frames,
        job_id=job_id,
        status=status,
        user=resolved_user,
        message=message,
        chunk_size=resolved_chunk,
    )

    if status == "not_implemented":
        detail = message or f"{farm_type.title()} adapter is not implemented yet."
        typer.secho(f"Render adapter response: {detail}", fg=typer.colors.YELLOW)
        return

    typer.secho(
        f"Submitted {dcc} scene '{scene}' to {farm_type} with job ID {job_id} (status: {status}).",
        fg=typer.colors.GREEN,
    )

    if message:
        typer.secho(message, fg=typer.colors.GREEN)


@presets_app.command("list")
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


@presets_app.command("save")
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
) -> None:
    """Persist a render submission preset to disk."""

    farm = farm.lower()
    resolved_dcc = dcc.lower() if dcc else None

    resolved_priority, resolved_chunk, _ = _resolve_priority_and_chunk_size(
        farm=farm,
        priority=priority,
        chunk_size=chunk_size,
    )

    payload: dict[str, Any] = {
        "farm": farm,
        "priority": resolved_priority,
    }
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


@presets_app.command("use")
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
    )
