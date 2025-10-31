"""Registry for operational Wrangler scripts exposed via the dashboard API."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Mapping, MutableMapping

from pydantic import BaseModel, Field


class WranglerScriptMetadata(BaseModel):
    """Describes a Wrangler script surfaced by the dashboard."""

    script_id: str = Field(
        ..., pattern=r"^[A-Za-z0-9._-]+$", description="Stable identifier"
    )
    name: str
    description: str | None = None
    tags: tuple[str, ...] = ()


class WranglerScriptResult(BaseModel):
    """Structured result returned from executing a Wrangler script."""

    script_id: str
    status: str = Field(default="success", pattern=r"^(success|error)$")
    message: str | None = None
    payload: Any | None = None


AwaitableResult = (
    Awaitable[WranglerScriptResult | Mapping[str, Any] | None]
    | WranglerScriptResult
    | Mapping[str, Any]
    | None
)


@dataclass(slots=True)
class _RegisteredScript:
    metadata: WranglerScriptMetadata
    runner: Callable[[], AwaitableResult]


_scripts: MutableMapping[str, _RegisteredScript] = OrderedDict()


async def _coerce_result(
    script_id: str, result: WranglerScriptResult | Mapping[str, Any] | None
) -> WranglerScriptResult:
    if isinstance(result, WranglerScriptResult):
        if result.script_id != script_id:
            return result.model_copy(update={"script_id": script_id})
        return result

    payload: Mapping[str, Any] | None
    if result is None:
        payload = None
    else:
        payload = dict(result)

    status = "success"
    message = None
    if isinstance(payload, Mapping) and payload.get("status") in {"error", "success"}:
        status = str(payload.get("status"))
        message = (
            payload.get("message") if isinstance(payload.get("message"), str) else None
        )

    return WranglerScriptResult(
        script_id=script_id, status=status, message=message, payload=payload
    )


async def execute_script(script_id: str) -> WranglerScriptResult:
    registered = _scripts.get(script_id)
    if not registered:
        raise KeyError(script_id)

    try:
        outcome = registered.runner()
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
    except Exception as exc:  # pragma: no cover - defensive, surfaced via API tests
        return WranglerScriptResult(
            script_id=script_id, status="error", message=str(exc)
        )

    return await _coerce_result(script_id, outcome)  # type: ignore[arg-type]


def register_script(
    metadata: WranglerScriptMetadata, runner: Callable[[], AwaitableResult]
) -> None:
    if metadata.script_id in _scripts:
        raise ValueError(
            f"Wrangler script '{metadata.script_id}' is already registered"
        )
    _scripts[metadata.script_id] = _RegisteredScript(metadata=metadata, runner=runner)


def iter_registered_scripts() -> Iterable[WranglerScriptMetadata]:
    for entry in _scripts.values():
        yield entry.metadata


def get_registered_script(script_id: str) -> _RegisteredScript | None:
    return _scripts.get(script_id)


def _reset_registry() -> None:
    _scripts.clear()
    _register_builtin_scripts()


def _register_builtin_scripts() -> None:
    from .scripts import cost, production, telemetry

    builtins = [
        (
            WranglerScriptMetadata(
                script_id="analyse_cost_drivers",
                name="Analyse cost drivers",
                description="Highlight the strongest cost inputs and optimisation levers",
                tags=("cost", "insights", "telemetry"),
            ),
            cost._run_analyse_cost_drivers_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="explain_pnl_delta",
                name="Explain P&L delta",
                description=(
                    "Contrast baseline vs current render spend and rank the delta drivers"
                ),
                tags=("finance", "pnl", "insights"),
            ),
            cost._run_explain_pnl_delta_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="evaluate_optimisation_playbook",
                name="Evaluate optimisation playbook",
                description=(
                    "Compare baseline costs with standard optimisation levers "
                    "to highlight the strongest projected savings"
                ),
                tags=("cost", "optimisation", "playbook"),
            ),
            cost._run_evaluate_optimisation_playbook_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="boost_gpu_utilisation",
                name="Boost GPU utilisation",
                description="Analyse render telemetry to lift GPU usage",
                tags=("rendering", "utilisation"),
            ),
            telemetry._run_boost_gpu_utilisation_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="audit_telemetry_coverage",
                name="Audit telemetry coverage",
                description=(
                    "Cross-check telemetry against render metrics to flag stale or missing shots"
                ),
                tags=("telemetry", "coverage", "health"),
            ),
            telemetry._run_audit_telemetry_coverage_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="check_telemetry_freshness",
                name="Check telemetry freshness",
                description="Measure the delay since the last ingest of render telemetry",
                tags=("telemetry", "health"),
            ),
            telemetry._run_check_telemetry_freshness_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="spin_down_idle_workers",
                name="Spin down idle GPU workers",
                description=(
                    "Recommend reducing GPU nodes when utilisation drops below the target band"
                ),
                tags=("rendering", "capacity", "cost"),
            ),
            production._run_spin_down_idle_workers_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="list_failing_jobs",
                name="List failing jobs",
                description="Surface critical shots breaching risk thresholds",
                tags=("risk", "shots"),
            ),
            production._run_list_failing_jobs_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="flag_frame_time_regressions",
                name="Flag frame time regressions",
                description=(
                    "Compare sequence frame times against the baseline and surface regressions"
                ),
                tags=("rendering", "performance"),
            ),
            production._run_flag_frame_time_regressions_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="flag_render_volatility",
                name="Flag render volatility hotspots",
                description=(
                    "Rank volatile shots with frame time swings and suggested follow-up"
                ),
                tags=("rendering", "utilisation"),
            ),
            production._run_flag_render_volatility_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="flag_render_error_streaks",
                name="Flag render error streaks",
                description=(
                    "Highlight shots with consecutive render errors and next steps"
                ),
                tags=("rendering", "errors", "shots"),
            ),
            production._run_flag_render_error_streaks_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="rebuild_unstable_caches",
                name="Rebuild unstable caches",
                description="Target shots with low cache stability and propose remedial actions",
                tags=("risk", "caches", "simulation"),
            ),
            production._run_rebuild_unstable_caches_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="escalate_deadline_shots",
                name="Escalate deadline-sensitive shots",
                description=(
                    "Highlight shots with deadline pressure and propose production follow-up"
                ),
                tags=("risk", "shots", "deadline"),
            ),
            production._run_escalate_deadline_shots_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="identify_unowned_shots",
                name="Identify unassigned shots",
                description=(
                    "Surface active shots whose current stage lacks an assigned owner"
                ),
                tags=("production", "shots", "ownership"),
            ),
            production._run_identify_unowned_shots_script,
        ),
        (
            WranglerScriptMetadata(
                script_id="highlight_stage_bottlenecks",
                name="Highlight stage bottlenecks",
                description=(
                    "Identify the busiest stage and flag the longest-stalled shots"
                ),
                tags=("production", "shots"),
            ),
            production._run_highlight_stage_bottlenecks_script,
        ),
    ]

    for metadata, runner in builtins:
        if metadata.script_id not in _scripts:
            register_script(metadata, runner)


_register_builtin_scripts()


__all__ = [
    "AwaitableResult",
    "WranglerScriptMetadata",
    "WranglerScriptResult",
    "execute_script",
    "get_registered_script",
    "iter_registered_scripts",
    "register_script",
    "_reset_registry",
]
