"""Typer commands exposing Maya animation helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import structlog
import typer

from apps.onepiece.utils.errors import OnePieceValidationError
from libraries.dcc.maya.animation_debugger import debug_animation
from libraries.dcc.maya.maya import cleanup_scene
from libraries.dcc.maya.playblast_tool import PlayblastAutomationTool, PlayblastRequest


log = structlog.get_logger(__name__)
app = typer.Typer(help="Animation focused DCC commands.")


def _load_metadata(path: Path | None) -> Mapping[str, Any]:
    if path is None:
        return {}

    try:
        raw = path.read_text()
    except OSError as exc:  # pragma: no cover - surfaced via Typer.
        raise typer.BadParameter(f"Unable to read metadata file: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:  # pragma: no cover - surfaced via Typer.
        raise typer.BadParameter(f"Invalid metadata JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise typer.BadParameter("Metadata JSON must contain an object")

    return data


def _create_playblast_tool() -> PlayblastAutomationTool:
    return PlayblastAutomationTool()


@app.command("debug-animation")
def run_debug_animation(
    scene_name: str = typer.Option(
        "current",
        "--scene-name",
        "-s",
        help="Friendly name for the Maya scene being analysed.",
    ),
    fail_on_warnings: bool = typer.Option(
        False,
        "--fail-on-warnings/--allow-warnings",
        help="Exit with an error when warnings are detected.",
    ),
) -> None:
    """Run the Maya animation debugger and surface any issues."""

    report = debug_animation(scene_name=scene_name)
    issues = [
        {"code": issue.code, "message": issue.message, "severity": issue.severity}
        for issue in getattr(report, "issues", ())
    ]

    if not issues:
        log.info("dcc_animation_debug_clean", scene=scene_name)
        typer.echo(f"No animation issues detected for {scene_name}.")
        return

    error_count = sum(1 for issue in issues if issue["severity"] == "error")
    log.warning(
        "dcc_animation_debug_issues",
        scene=scene_name,
        issues=issues,
        error_count=error_count,
    )

    typer.echo(f"Animation issues for {scene_name}:")
    for issue in issues:
        severity = issue["severity"].upper()
        typer.echo(f"- [{severity}] {issue['code']}: {issue['message']}")

    if error_count or fail_on_warnings:
        raise OnePieceValidationError(
            f"Animation issues detected for {scene_name}; see log for details."
        )


@app.command("cleanup-scene")
def run_cleanup_scene(
    remove_unused_references: bool = typer.Option(
        True,
        "--remove-unused-references/--keep-unused-references",
        help="Remove references that no longer contribute nodes to the scene.",
    ),
    clean_namespaces: bool = typer.Option(
        True,
        "--clean-namespaces/--keep-namespaces",
        help="Delete empty namespaces created during imports.",
    ),
    optimize_layers: bool = typer.Option(
        True,
        "--optimize-layers/--keep-layers",
        help="Prune empty display and render layers.",
    ),
    prune_unknown_nodes: bool = typer.Option(
        True,
        "--prune-unknown-nodes/--keep-unknown-nodes",
        help="Remove unknown nodes that can destabilise a scene.",
    ),
) -> None:
    """Run Maya scene cleanup helpers with configurable operations."""

    if not any(
        (
            remove_unused_references,
            clean_namespaces,
            optimize_layers,
            prune_unknown_nodes,
        )
    ):
        raise typer.BadParameter("At least one cleanup operation must be enabled")

    stats = cleanup_scene(
        remove_unused_references=remove_unused_references,
        clean_namespaces=clean_namespaces,
        optimize_layers=optimize_layers,
        prune_unknown_nodes=prune_unknown_nodes,
    )

    log.info("dcc_animation_cleanup_summary", operations=stats)

    if not stats:
        typer.echo("Cleanup completed; no changes were required.")
        return

    typer.echo("Cleanup summary:")
    for key, value in stats.items():
        typer.echo(f"- {key}: {value}")


@app.command("playblast")
def trigger_playblast(
    project: str = typer.Option(
        ..., "--project", help="Project code for the playblast."
    ),
    shot: str = typer.Option(..., "--shot", help="Shot identifier."),
    artist: str = typer.Option(
        ..., "--artist", help="Artist generating the playblast."
    ),
    camera: str = typer.Option(..., "--camera", help="Camera used for rendering."),
    version: int = typer.Option(
        ..., "--version", min=0, help="Playblast version number."
    ),
    output_directory: str = typer.Option(
        ...,
        "--output-directory",
        dir_okay=True,
        file_okay=False,
        path_type=str,
        help="Directory where the playblast should be written.",
    ),
    sequence: str | None = typer.Option(
        None, "--sequence", help="Optional sequence identifier."
    ),
    format: str = typer.Option(
        "mov", "--format", help="File format for the playblast."
    ),
    codec: str = typer.Option("h264", "--codec", help="Codec used when rendering."),
    width: int = typer.Option(1920, "--width", min=1, help="Output width in pixels."),
    height: int = typer.Option(
        1080, "--height", min=1, help="Output height in pixels."
    ),
    frame_start: int | None = typer.Option(
        None, "--frame-start", help="First frame to capture."
    ),
    frame_end: int | None = typer.Option(
        None, "--frame-end", help="Last frame to capture."
    ),
    description: str | None = typer.Option(
        None, "--description", help="Optional playblast description."
    ),
    include_audio: bool = typer.Option(
        False,
        "--include-audio/--mute",
        help="Include audio during playblast generation.",
    ),
    metadata: Path | None = typer.Option(
        None,
        "--metadata",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Optional JSON file containing extra metadata.",
    ),
) -> None:
    """Trigger a Maya playblast job via :class:`PlayblastAutomationTool`."""

    if (frame_start is None) != (frame_end is None):
        raise typer.BadParameter("frame-start and frame-end must be provided together")

    extra_metadata = _load_metadata(metadata)

    try:
        request = PlayblastRequest(
            project=project,
            sequence=sequence,
            shot=shot,
            artist=artist,
            camera=camera,
            version=version,
            output_directory=Path(output_directory),
            format=format,
            codec=codec,
            resolution=(width, height),
            frame_range=(frame_start, frame_end) if frame_start is not None else None,
            description=description,
            include_audio=include_audio,
            extra_metadata=extra_metadata,
        )
    except ValueError as exc:
        raise OnePieceValidationError(str(exc)) from exc

    tool = _create_playblast_tool()
    result = tool.execute(request)

    log.info(
        "dcc_animation_playblast_complete",
        path=str(result.output_path),
        frame_start=result.frame_range[0],
        frame_end=result.frame_range[1],
    )

    typer.echo(f"Playblast generated at {result.output_path}")

    if result.shotgrid_version:
        version_code = result.shotgrid_version.get("code")
        typer.echo(f"ShotGrid Version: {version_code}")

    if result.review_id:
        typer.echo(f"Review ID: {result.review_id}")


__all__ = ["app", "run_debug_animation", "run_cleanup_scene", "trigger_playblast"]
