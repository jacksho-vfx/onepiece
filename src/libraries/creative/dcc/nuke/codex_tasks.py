"""Codex tasks scoped to Nuke."""

from __future__ import annotations

from libraries.creative.dcc.codex import CodexTask


NUKE_CODEX_TASKS: tuple[CodexTask, ...] = (
    CodexTask(
        slug="nuke-usd-review-template",
        title="USD Review Template",
        dcc="Nuke",
        description=(
            "Build a USD-aware Nuke template that auto-wires plates, cameras, and "
            "render contexts for dailies."
        ),
        problem=(
            "Comp artists burn time rebuilding read nodes, camera imports, and OCIO "
            "configs whenever a layout update lands."
        ),
        approach=(
            "Load latest USD camera and render context from the registry and bind "
            "them to a templated node graph.",
            "Auto-align plates to USD camera metadata (resolution, shutter, color "
            "pipeline) and drop review watermarks.",
            "Expose toggles for Hydra/GL previews and utility mattes without "
            "breaking the template.",
        ),
        deliverables=(
            "Nuke gizmo/template that pulls USD context",
            "Helper script to resolve latest plates and caches",
            "Review-friendly write nodes with naming enforcement",
        ),
        dependencies=("OCIO", "USD camera readers", "Show plate conventions"),
    ),
    CodexTask(
        slug="nuke-aov-debugger",
        title="AOV Debugger",
        dcc="Nuke",
        description=(
            "Create a diagnostic panel that inspects USD render products and builds "
            "contact sheets for problematic AOVs."
        ),
        problem=(
            "Lighting publishes frequently miss expected cryptomatte or utility AOVs, "
            "and comps discover it too late in the day."
        ),
        approach=(
            "Parse the USD render product definitions and compare them against show "
            "expectations.",
            "Assemble preview stacks or contact sheets for flagged AOVs (e.g. "
            "blown-out normals, missing cryptomattes).",
            "Offer one-click tickets or Slack-ready summaries for the lighting team "
            "with frames and render settings attached.",
        ),
        deliverables=(
            "Diagnostic viewer panel",
            "Automated contact sheet generator",
            "Reporting hook to messaging or ticketing",
        ),
        dependencies=("USD render products", "Nuke python panel API"),
    ),
)

__all__ = ["NUKE_CODEX_TASKS"]
