"""Unit tests for the UTA web command metadata helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path

import click
import pytest
from py_mini_racer.py_mini_racer import MiniRacer

from apps.uta import web


def test_required_option_omits_placeholder_default() -> None:
    """Required options should not display sentinel defaults."""

    @click.command()
    @click.option("--foo", required=True, help="Example option")
    def cli(foo: str) -> None:  # pragma: no cover - executed via metadata extraction
        raise NotImplementedError

    parameters = web._extract_parameters(cli)
    assert parameters, "Expected the command to expose at least one parameter"

    parameter = parameters[0]
    assert parameter.required is True
    assert parameter.default is None

    rendered = web._render_parameters(
        web.CommandSpec(path=["cli"], summary="", parameters=parameters)
    )

    assert "required" in rendered
    assert "default:" not in rendered
    assert "Ellipsis" not in rendered


def test_dashboard_chart_builders() -> None:
    """Inline dashboard script should expose test hooks for chart configs."""

    html = web._render_index("/")
    script_matches = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    assert script_matches, "Expected inline script block to be rendered"
    inline_script = script_matches[-1]

    assert "window.utaDashboardTestHooks" in inline_script

    try:
        from py_mini_racer import py_mini_racer

        context: MiniRacer = py_mini_racer.MiniRacer()
    except (RuntimeError, ImportError) as exc:
        pytest.skip(f"MiniRacer native binary not available: {exc}")

    context.eval(
        "var window = this;"
        "window.window = window;"
        "window.console = { log: function(){}, warn: function(){}, error: function(){} };"
    )
    functions_snippet = (
        "const colourPalette"
        + inline_script.split("const colourPalette", 1)[1].split(
            "window.utaDashboardTestHooks", 1
        )[0]
    )
    context.eval(functions_snippet)
    context.eval(
        "window.utaDashboardTestHooks = {"
        " buildStatusBreakdownConfig: buildStatusBreakdownConfig,"
        " buildThroughputConfig: buildThroughputConfig,"
        " buildAdapterUtilisationConfig: buildAdapterUtilisationConfig,"
        " normaliseWindowLabel: normaliseWindowLabel"
        " };"
    )

    fixture_path = Path("docs/examples/trafalgar_render_metrics.json")
    metrics_fixture = json.loads(fixture_path.read_text())

    status_config = context.call(
        "window.utaDashboardTestHooks.buildStatusBreakdownConfig",
        metrics_fixture["statuses"],
    )
    throughput_config = context.call(
        "window.utaDashboardTestHooks.buildThroughputConfig",
        metrics_fixture["submission_windows"],
    )
    adapter_config = context.call(
        "window.utaDashboardTestHooks.buildAdapterUtilisationConfig",
        metrics_fixture["adapters"],
    )
    empty_status = context.call(
        "window.utaDashboardTestHooks.buildStatusBreakdownConfig",
        {"queued": {"count": 0}},
    )
    normalised = context.call(
        "window.utaDashboardTestHooks.normaliseWindowLabel",
        "1h",
    )

    assert empty_status is None
    assert normalised == "Past hour"

    assert status_config["type"] == "doughnut"
    assert status_config["data"]["labels"] == [
        "completed",
        "failed",
        "queued",
        "running",
    ]
    assert status_config["data"]["datasets"][0]["data"] == [6, 1, 4, 7]

    assert throughput_config["type"] == "line"
    assert throughput_config["data"]["labels"] == [
        "Past hour",
        "Past 6 hours",
        "Past day",
        "Past week",
    ]
    assert throughput_config["data"]["datasets"][0]["data"] == [3, 7, 14, 18]

    assert adapter_config["type"] == "bar"
    assert adapter_config["data"]["labels"] == ["mock", "deadline", "tractor"]
    assert adapter_config["data"]["datasets"][0]["data"] == [9, 5, 4]
