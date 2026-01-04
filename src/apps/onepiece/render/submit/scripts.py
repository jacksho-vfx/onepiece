"""Utilities for generating render submission helper scripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Any

import structlog

from apps.onepiece.utils.errors import (
    OnePieceExternalServiceError,
    OnePieceRuntimeError,
    OnePieceValidationError,
)
from libraries.automation.render.base import RenderSubmissionError

from .helpers import (
    DCC_CHOICES,
    FARM_CHOICES,
    get_adapter,
    parse_frame_count,
    resolve_metrics,
    resolve_priority_and_chunk_size,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RenderScriptBundle:
    """Collection of helper scripts for DCC panels and menus."""

    panel: str
    menu: str
    optimizer: str
    sanity_checker: str


def _decision_to_dict(decision: Any | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    return {
        "priority": decision.priority,
        "chunk_size": decision.chunk_size,
        "applied": decision.applied,
        "reasons": list(decision.reasons),
    }


def sanity_check_submission(
    *, scene: Path, output: Path, frames: str
) -> dict[str, Any]:
    """Return a structured sanity check report for a render submission."""

    errors: list[str] = []

    if not scene.exists():
        errors.append(f"Scene file '{scene}' does not exist.")
    elif not scene.is_file():
        errors.append(f"Scene path '{scene}' is not a file.")

    if not output.exists():
        errors.append(f"Output directory '{output}' does not exist.")
    elif not output.is_dir():
        errors.append(f"Output path '{output}' is not a directory.")

    frame_count = parse_frame_count(frames)
    if frame_count is None:
        errors.append(f"Frame range '{frames}' is invalid.")

    return {
        "ok": not errors,
        "errors": tuple(errors),
        "frame_count": frame_count,
    }


def optimisation_preview(
    *,
    dcc: str,
    farm: str,
    frames: str,
    profile: str | None = None,
    queue_depth: int | None = None,
    average_frame_ms: float | None = None,
    optimize: bool = True,
) -> dict[str, Any]:
    """Summarise optimisation decisions without submitting a job."""

    farm = farm.lower()
    dcc = dcc.lower()
    frame_count = parse_frame_count(frames)
    metrics, metric_sources = resolve_metrics(
        optimize=optimize,
        profile_name=profile,
        queue_depth=queue_depth,
        average_frame_ms=average_frame_ms,
    )

    (
        resolved_priority,
        resolved_chunk,
        capabilities,
        decision,
    ) = resolve_priority_and_chunk_size(
        farm=farm,
        priority=None,
        chunk_size=None,
        frame_count=frame_count,
        optimize=optimize,
        metrics=metrics,
    )

    return {
        "dcc": dcc,
        "farm": farm,
        "frame_count": frame_count,
        "capabilities": capabilities,
        "decision": _decision_to_dict(decision),
        "metrics_source": tuple(metric_sources),
        "priority": resolved_priority,
        "chunk_size": resolved_chunk,
    }


def run_render_submission(
    *,
    dcc: str,
    farm: str,
    scene: Path,
    frames: str,
    output: Path,
    user: str | None = None,
    profile: str | None = None,
    queue_depth: int | None = None,
    average_frame_ms: float | None = None,
    optimize: bool = True,
) -> dict[str, Any]:
    """Submit a render job while applying optimisation heuristics."""

    sanity = sanity_check_submission(scene=scene, output=output, frames=frames)
    if not sanity["ok"]:
        raise OnePieceValidationError("; ".join(sanity["errors"]))

    preview = optimisation_preview(
        dcc=dcc,
        farm=farm,
        frames=frames,
        profile=profile,
        queue_depth=queue_depth,
        average_frame_ms=average_frame_ms,
        optimize=optimize,
    )

    adapter = get_adapter(farm.lower())
    resolved_user = user or ""

    try:
        result = adapter(
            scene=str(scene),
            frames=frames,
            output=str(output),
            dcc=dcc.lower(),
            priority=preview["priority"],
            user=resolved_user,
            chunk_size=preview["chunk_size"],
        )
    except RenderSubmissionError as exc:
        log.error(
            "render.scripts.submit_failed",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
            frames=frames,
            error=str(exc),
        )
        raise OnePieceExternalServiceError(f"Render submission failed: {exc}") from exc
    except Exception as exc:  # pragma: no cover - defensive programming
        log.exception(
            "render.scripts.unexpected_error",
            dcc=dcc,
            farm=farm,
            scene=str(scene),
        )
        raise OnePieceRuntimeError(
            "Render submission failed due to an unexpected error."
        ) from exc

    return {
        "result": dict(result),
        "decision": preview["decision"],
        "capabilities": preview["capabilities"],
        "metrics_source": preview["metrics_source"],
    }


def _format_header(summary: str) -> str:
    return dedent(
        f'''
        """
        {summary}
        Generated by the OnePiece render CLI so DCC panels and menus can call
        optimised submission helpers without reimplementing heuristics.
        """
        '''
    ).strip()


def _panel_template(dcc: str, farm: str, profile: str | None) -> str:
    profile_repr = repr(profile)
    header = _format_header(f"Panel submission helper for {dcc.title()}.")
    return dedent(
        f'''
        {header}

        from pathlib import Path

        from apps.onepiece.render.submit.scripts import run_render_submission


        def submit_render(scene: str, frames: str, output: str, user: str | None = None) -> dict:
            """Submit a render job with OnePiece defaults from a DCC panel."""

            return run_render_submission(
                dcc="{dcc}",
                farm="{farm}",
                scene=Path(scene),
                frames=frames,
                output=Path(output),
                user=user,
                profile={profile_repr},
            )
        '''
    )


def _menu_template(dcc: str, farm: str, profile: str | None) -> str:
    profile_repr = repr(profile)
    header = _format_header(f"Menu action wrapper for {dcc.title()}.")
    return dedent(
        f'''
        {header}

        from pathlib import Path

        from apps.onepiece.render.submit.scripts import run_render_submission, sanity_check_submission


        def menu_action(scene: str, frames: str, output: str, user: str | None = None) -> dict:
            """Menu-friendly submission entrypoint with sanity checks."""

            report = sanity_check_submission(
                scene=Path(scene),
                output=Path(output),
                frames=frames,
            )
            if not report["ok"]:
                return report

            submission = run_render_submission(
                dcc="{dcc}",
                farm="{farm}",
                scene=Path(scene),
                frames=frames,
                output=Path(output),
                user=user,
                profile={profile_repr},
            )
            submission["sanity"] = report
            return submission
        '''
    )


def _optimization_template(dcc: str, farm: str, profile: str | None) -> str:
    profile_repr = repr(profile)
    header = _format_header(f"Optimisation helper for {dcc.title()} submissions.")
    return dedent(
        f'''
        {header}

        from apps.onepiece.render.submit.scripts import optimisation_preview


        def preview_submission(frames: str, queue_depth: int | None = None, average_frame_ms: float | None = None) -> dict:
            """Return priority/chunk-size recommendations without submitting."""

            return optimisation_preview(
                dcc="{dcc}",
                farm="{farm}",
                frames=frames,
                profile={profile_repr},
                queue_depth=queue_depth,
                average_frame_ms=average_frame_ms,
            )
        '''
    )


def _sanity_template() -> str:
    header = _format_header("Standalone sanity checker for renders.")
    return dedent(
        f'''
        {header}

        from pathlib import Path

        from apps.onepiece.render.submit.scripts import sanity_check_submission


        def sanity_check(scene: str, frames: str, output: str) -> dict:
            """Validate paths and frame ranges before dispatching a render."""

            return sanity_check_submission(
                scene=Path(scene),
                output=Path(output),
                frames=frames,
            )
        '''
    )


def build_render_script_bundle(
    *, dcc: str, farm: str, profile: str | None = None
) -> RenderScriptBundle:
    """Create scripts that wrap OnePiece render helpers for DCC tooling."""

    if dcc.lower() not in DCC_CHOICES:
        raise OnePieceValidationError(f"Unknown DCC '{dcc}'.")
    if farm.lower() not in FARM_CHOICES:
        raise OnePieceValidationError(f"Unknown render farm '{farm}'.")

    return RenderScriptBundle(
        panel=_panel_template(dcc.lower(), farm.lower(), profile),
        menu=_menu_template(dcc.lower(), farm.lower(), profile),
        optimizer=_optimization_template(dcc.lower(), farm.lower(), profile),
        sanity_checker=_sanity_template(),
    )


def _write_script(path: Path, content: str, *, overwrite: bool) -> Path:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing script '{path}'. "
            "Re-run with overwrite enabled."
        )
    path.write_text(content)
    return path


def write_render_script_bundle(
    bundle: RenderScriptBundle,
    destination: Path,
    *,
    overwrite: bool = False,
) -> tuple[Path, ...]:
    """Persist helper scripts to ``destination`` for DCC deployment."""

    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    written.append(
        _write_script(
            destination / "panel_submission.py", bundle.panel, overwrite=overwrite
        )
    )
    written.append(
        _write_script(
            destination / "menu_submission.py", bundle.menu, overwrite=overwrite
        )
    )
    written.append(
        _write_script(
            destination / "optimisation_helper.py",
            bundle.optimizer,
            overwrite=overwrite,
        )
    )
    written.append(
        _write_script(
            destination / "sanity_checker.py",
            bundle.sanity_checker,
            overwrite=overwrite,
        )
    )
    return tuple(written)


__all__ = [
    "RenderScriptBundle",
    "build_render_script_bundle",
    "optimisation_preview",
    "run_render_submission",
    "sanity_check_submission",
    "write_render_script_bundle",
]
