"""Typer commands for Cinema 4D package workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar, cast

import structlog
import typer

from libraries.creative.dcc.cinema4d.cleanup import cleanup_scene
from libraries.creative.dcc.cinema4d.gather import gather_references
from libraries.creative.dcc.cinema4d.metadata import (
    SUMMARY_ENV_VAR,
    load_cinema4d_summary,
)
from libraries.creative.dcc.cinema4d.script_library import (
    default_script_directory,
    deploy_scripts_to_directory,
    discover_cinema4d_scripts,
)
from libraries.creative.dcc.cinema4d.validation import (
    normalise_asset_paths,
    validate_package,
)

log = structlog.get_logger(__name__)
app = typer.Typer(name="cinema4d", help="Cinema 4D integration commands")
T = TypeVar("T")


def _resolve_override(name: str, default: T) -> T:
    from apps.onepiece.dcc import cinema4d as cinema4d_module

    override = getattr(cinema4d_module, name, None)
    if override is not None and override is not default:
        return cast(T, override)
    return default


def _format_issues(issues: list[str]) -> str:
    """Return a human readable bullet list for validation issues."""

    bullets = "\n".join(f"- {entry}" for entry in issues)
    return (
        f"Cinema 4D package validation detected issues:\n{bullets}" if bullets else ""
    )


@app.command()
def validate(
    package_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Path to the Cinema 4D package directory",
    ),
) -> None:
    """Validate a packaged Cinema 4D scene directory."""

    log.info("cinema4d.validate.start", package=str(package_dir))
    issues = list(_resolve_override("validate_package", validate_package)(package_dir))

    if not issues:
        message = f"Cinema 4D package at {package_dir} passed validation."
        typer.secho(message, fg=typer.colors.GREEN)
        log.info("cinema4d.validate.success", package=str(package_dir))
        return

    typer.secho(_format_issues(issues), fg=typer.colors.RED)
    log.error("cinema4d.validate.failed", package=str(package_dir), issues=issues)
    raise typer.Exit(code=1)


def _format_frame_range(frame_range: Any) -> str:
    if frame_range is None:
        return "Not specified"

    if isinstance(frame_range, (list, tuple)) and len(frame_range) == 2:
        start, end = frame_range
        return f"{start} - {end}"

    return str(frame_range)


@app.command("show-summary")
def show_summary(
    summary_path: Path | None = typer.Argument(
        None,
        help=(
            "Optional path to a Cinema 4D summary JSON file. When omitted the value "
            f"is resolved from ${SUMMARY_ENV_VAR}."
        ),
    ),
) -> None:
    """Display the Cinema 4D metadata summary parsed from disk."""

    log.info(
        "cinema4d.show_summary.start",
        summary_path=str(summary_path) if summary_path is not None else None,
    )

    env_override: dict[str, str] | None = None
    if summary_path is not None:
        env_override = {SUMMARY_ENV_VAR: str(summary_path)}

    summary = load_cinema4d_summary(env=env_override)
    if not summary:
        message = "No Cinema 4D summary metadata is available."
        typer.secho(message, fg=typer.colors.RED)
        log.warning("cinema4d.show_summary.missing")
        raise typer.Exit(code=1)

    frame_range = _format_frame_range(summary.get("frame_range"))
    renderer = summary.get("renderer") or "Not specified"
    take = summary.get("take") or "Not specified"
    extras = {
        key: value
        for key, value in summary.items()
        if key not in {"frame_range", "renderer", "take"}
    }

    lines = [
        "Cinema 4D Summary",
        f"  Frame range: {frame_range}",
        f"  Renderer: {renderer}",
        f"  Take: {take}",
    ]

    if extras:
        lines.append("  Extra metadata:")
        for key in sorted(extras):
            value = extras[key]
            lines.append(f"    {key}: {value}")

    typer.echo("\n".join(lines))
    log.info("cinema4d.show_summary.success", summary_keys=sorted(summary))


def _format_cleanup_summary(stats: dict[str, int]) -> str:
    return (
        "Removed "
        f"{stats.get('removed_materials', 0)} materials, "
        f"{stats.get('removed_empty_nulls', 0)} nulls, "
        f"{stats.get('removed_hidden_singletons', 0)} hidden objects, "
        f"{stats.get('removed_layers', 0)} layers."
    )


@app.command("cleanup-scene")
def run_cleanup_scene(
    remove_unused_materials: bool = typer.Option(
        True,
        "--remove-unused-materials/--keep-unused-materials",
        help="Remove materials that are no longer assigned to any objects.",
    ),
    remove_empty_nulls: bool = typer.Option(
        True,
        "--remove-empty-nulls/--keep-empty-nulls",
        help="Delete null objects that do not contain children.",
    ),
    remove_hidden_singletons: bool = typer.Option(
        True,
        "--remove-hidden-singletons/--keep-hidden-singletons",
        help="Delete hidden objects that do not contain children.",
    ),
    remove_unused_layers: bool = typer.Option(
        True,
        "--remove-unused-layers/--keep-unused-layers",
        help="Remove unused layer entries that no longer have assignments.",
    ),
) -> None:
    """Run Cinema 4D scene cleanup helpers."""

    operations = {
        "remove_unused_materials": remove_unused_materials,
        "remove_empty_nulls": remove_empty_nulls,
        "remove_hidden_singletons": remove_hidden_singletons,
        "remove_unused_layers": remove_unused_layers,
    }

    if not any(operations.values()):
        raise typer.BadParameter("At least one cleanup operation must be enabled")

    log.info("cinema4d.cleanup_scene.start", operations=operations)
    stats = _resolve_override("cleanup_scene", cleanup_scene)(**operations)
    summary = _format_cleanup_summary(stats)
    typer.echo(f"Cinema 4D cleanup complete. {summary}")
    log.info("cinema4d.cleanup_scene.summary", **stats)


def _format_asset_list(title: str, entries: tuple[str, ...]) -> str:
    bullet_list = "\n".join(f"  - {item}" for item in entries)
    return f"{title}:\n{bullet_list}"


@app.command("gather-assets")
def gather_assets(
    package_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Path to the Cinema 4D package directory",
    ),
    source_dir: Path | None = typer.Argument(
        None,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Optional source directory containing referenced assets",
    ),
) -> None:
    """Copy referenced textures and presets into the package directory."""

    log.info(
        "cinema4d.gather_assets.start",
        package=str(package_dir),
        source=str(source_dir) if source_dir is not None else None,
    )

    result = _resolve_override("gather_references", gather_references)(
        package_dir, source_root=source_dir
    )

    if result.copied:
        typer.secho(_format_asset_list("Copied assets", result.copied))

    if result.missing:
        typer.secho(
            _format_asset_list("Missing assets", result.missing),
            fg=typer.colors.RED,
        )

    if result.issues:
        typer.secho(
            "Cinema 4D reference issues detected:\n"
            + "\n".join(f"- {issue}" for issue in result.issues),
            fg=typer.colors.RED,
        )

    log_data = {
        "package": str(package_dir),
        "source": str(source_dir) if source_dir is not None else None,
        "copied": result.copied,
        "missing": result.missing,
        "issues": result.issues,
    }

    if result.missing or result.issues:
        log.warning("cinema4d.gather_assets.incomplete", **log_data)
        raise typer.Exit(code=1)

    log.info("cinema4d.gather_assets.success", **log_data)


@app.command("normalise-paths")
def normalise_paths(
    package_dir: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        help="Path to the Cinema 4D package directory",
    ),
) -> None:
    """Rewrite Cinema 4D asset paths to be package relative."""

    log.info("cinema4d.normalise_paths.start", package=str(package_dir))

    result = normalise_asset_paths(package_dir)

    if result.metadata is None:
        message = (
            result.warnings[0]
            if result.warnings
            else ("Cinema 4D metadata could not be normalised.")
        )
        typer.secho(message, fg=typer.colors.RED)
        log.error(
            "cinema4d.normalise_paths.unavailable",
            package=str(package_dir),
            warnings=result.warnings,
        )
        raise typer.Exit(code=1)

    metadata_path = package_dir / "metadata.json"
    if result.updated:
        metadata_text = json.dumps(result.metadata, indent=2, sort_keys=True)
        metadata_path.write_text(metadata_text + "\n")

    if result.warnings:
        warning_lines = "\n".join(f"- {warning}" for warning in result.warnings)
        typer.secho(
            "Some asset paths still need manual attention:\n" + warning_lines,
            fg=typer.colors.YELLOW,
        )
        log.warning(
            "cinema4d.normalise_paths.partial",
            package=str(package_dir),
            updated=result.updated,
            warnings=result.warnings,
        )
        raise typer.Exit(code=1)

    if result.updated:
        typer.secho("Cinema 4D asset paths normalised.", fg=typer.colors.GREEN)
        log.info(
            "cinema4d.normalise_paths.success",
            package=str(package_dir),
            updated=True,
        )
        return

    typer.secho(
        "Cinema 4D asset paths were already normalised.",
        fg=typer.colors.GREEN,
    )
    log.info(
        "cinema4d.normalise_paths.noop",
        package=str(package_dir),
        updated=False,
    )


@app.command("deploy-to-cinema4d")
def deploy_scripts_to_cinema4d(
    destination: Path = typer.Argument(
        ...,
        help="Directory where Cinema 4D scripts should be copied for Cinema 4D.",
        exists=False,
        dir_okay=True,
        file_okay=False,
        writable=True,
        resolve_path=True,
    ),
    scripts_dir: Path | None = typer.Option(
        None,
        "--scripts",
        "-s",
        help=(
            "Optional path to the Cinema 4D scripts directory. Defaults to the "
            "bundled scripts shipped with the OnePiece toolkit."
        ),
        exists=False,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Copy Cinema 4D helper scripts into a Cinema 4D scripts directory."""

    source_dir = scripts_dir or default_script_directory()
    scripts = discover_cinema4d_scripts(source_dir)

    if not scripts:
        typer.secho(f"No Cinema 4D scripts found in {source_dir}.", fg=typer.colors.RED)
        log.warning(
            "cinema4d.deploy_to_cinema4d.missing_scripts", source=str(source_dir)
        )
        raise typer.Exit(code=1)

    copied = deploy_scripts_to_directory(destination, scripts)
    typer.secho(
        f"Copied {len(copied)} Cinema 4D scripts to {destination}.",
        fg=typer.colors.GREEN,
    )
    log.info(
        "cinema4d.deploy_to_cinema4d.success",
        destination=str(destination),
        scripts=[str(path) for path in copied],
    )


__all__ = [
    "app",
    "gather_assets",
    "normalise_paths",
    "run_cleanup_scene",
    "show_summary",
    "validate",
]
