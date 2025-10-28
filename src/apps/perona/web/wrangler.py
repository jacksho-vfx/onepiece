"""Registry for operational Wrangler scripts exposed via the dashboard API."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Mapping, MutableMapping

from pydantic import BaseModel, Field


class WranglerScriptMetadata(BaseModel):
    """Describes a Wrangler script surfaced by the dashboard."""

    script_id: str = Field(..., pattern=r"^[A-Za-z0-9._-]+$", description="Stable identifier")
    name: str
    description: str | None = None
    tags: tuple[str, ...] = ()


class WranglerScriptResult(BaseModel):
    """Structured result returned from executing a Wrangler script."""

    script_id: str
    status: str = Field(default="success", pattern=r"^(success|error)$")
    message: str | None = None
    payload: Any | None = None


AwaitableResult = Awaitable[WranglerScriptResult | Mapping[str, Any] | None] | WranglerScriptResult | Mapping[
    str, Any
] | None


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
        message = payload.get("message") if isinstance(payload.get("message"), str) else None

    return WranglerScriptResult(script_id=script_id, status=status, message=message, payload=payload)


async def execute_script(script_id: str) -> WranglerScriptResult:
    registered = _scripts.get(script_id)
    if not registered:
        raise KeyError(script_id)

    try:
        outcome = registered.runner()
        if asyncio.iscoroutine(outcome):
            outcome = await outcome
    except Exception as exc:  # pragma: no cover - defensive, surfaced via API tests
        return WranglerScriptResult(script_id=script_id, status="error", message=str(exc))

    return await _coerce_result(script_id, outcome)


def register_script(metadata: WranglerScriptMetadata, runner: Callable[[], AwaitableResult]) -> None:
    if metadata.script_id in _scripts:
        raise ValueError(f"Wrangler script '{metadata.script_id}' is already registered")
    _scripts[metadata.script_id] = _RegisteredScript(metadata=metadata, runner=runner)


def iter_registered_scripts() -> Iterable[WranglerScriptMetadata]:
    for entry in _scripts.values():
        yield entry.metadata


def get_registered_script(script_id: str) -> _RegisteredScript | None:
    return _scripts.get(script_id)


def _reset_registry() -> None:
    _scripts.clear()
