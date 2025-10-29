"""Tests for the pipeline runtime package.

This module doubles as a namespace for lightweight pipeline providers used by
the web API tests.  The Trafalgar pipeline API dynamically resolves providers
from dotted strings (``module:attribute``).  The test profile defined in
``src/tests/web/test_pipeline_api.py`` references ``tests.pipeline`` which
maps to this file.  The real project would normally expose rich provider
implementations, however for the purposes of exercising the API wiring we only
need deterministic callables that always succeed.

The helpers below accept the pipeline parameters mapping and simply echo a
payload describing the executed step.  Returning a mapping keeps the
``PipelineExecutor`` happy (it normalises the payload and treats it as an
event) while ensuring the orchestrator records predictable run metadata for
the assertions made in the tests.
"""

from __future__ import annotations

from typing import Any, Mapping


def _event_payload(step: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Return a simple payload describing the executed pipeline *step*.

    The payload mirrors the shape produced by real providers: the executor will
    detect the mapping, convert it into a :class:`StepTriggerEvent`, and the
    orchestrator will record the resulting metadata on the run.  Tests only
    assert that the pipeline completes successfully, so the exact structure is
    intentionally small and predictable.
    """

    return {
        "event": step,
        "payload": {"parameters": dict(parameters)},
    }


def prepare(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Dummy provider for the ``prepare`` pipeline step."""

    return _event_payload("prepare.completed", parameters)


def render(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Dummy provider for the ``render`` pipeline step."""

    return _event_payload("render.completed", parameters)


def publish(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Dummy provider for the ``publish`` pipeline step."""

    return _event_payload("publish.completed", parameters)


def notify(event: Any, parameters: Mapping[str, Any]) -> dict[str, Any]:
    """Dummy provider for the ``notify`` pipeline step."""

    event_name = getattr(event, "name", "")
    payload = getattr(event, "payload", {})
    return {
        "event": "notify.completed",
        "payload": {
            "source_event": event_name,
            "source_payload": dict(payload),
            "parameters": dict(parameters),
        },
    }


__all__ = ["prepare", "render", "publish", "notify"]
