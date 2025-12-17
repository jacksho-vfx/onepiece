"""Codex tasks scoped to Deadline render farm operations."""

from __future__ import annotations

from libraries.creative.dcc.codex import CodexTask


DEADLINE_CODEX_TASKS: tuple[CodexTask, ...] = (
    CodexTask(
        slug="deadline-usd-render-guard",
        title="USD Render Guard",
        dcc="Deadline",
        description=(
            "Preflight USD-based submissions for the farm, validating assets, OCIO, "
            "and GPU/CPU requirements before dispatch."
        ),
        problem=(
            "Farm time is wasted when submissions reference missing caches, wrong "
            "OCIO configs, or incompatible GPU plugins."
        ),
        approach=(
            "Inspect USD packages for required assets and plugins using the registry "
            "and packaging manifests.",
            "Cross-check render settings against farm pools (GPU/CPU, renderer "
            "versions) and suggest the appropriate Deadline group.",
            "Emit a ticket-ready report and optionally block submits that fail "
            "mandatory checks.",
        ),
        deliverables=(
            "Submission hook integrating with Deadline",
            "Validation report with auto-remediation tips",
            "Pool/group recommender for GPU vs CPU jobs",
        ),
        dependencies=("Deadline Python API", "USD packaging manifests", "OCIO"),
    ),
)

__all__ = ["DEADLINE_CODEX_TASKS"]
