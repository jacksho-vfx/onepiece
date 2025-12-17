"""Codex task definitions for archviz-friendly DCC tooling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodexTask:
    """Describe a self-contained tool idea for a DCC workflow."""

    slug: str
    title: str
    dcc: str
    description: str
    problem: str
    approach: tuple[str, ...]
    deliverables: tuple[str, ...]
    dependencies: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, str | tuple[str, ...]]:
        """Return a serialisable representation useful for docs or UIs."""

        return {
            "slug": self.slug,
            "title": self.title,
            "dcc": self.dcc,
            "description": self.description,
            "problem": self.problem,
            "approach": self.approach,
            "deliverables": self.deliverables,
            "dependencies": self.dependencies,
        }


CROSS_DCC_CODEX_TASKS: tuple[CodexTask, ...] = (
    CodexTask(
        slug="usd-lineage-registry",
        title="USD Lineage Registry",
        dcc="Cross-DCC",
        description=(
            "Track USD asset versions, variants, and approvals so every DCC can "
            "resolve canonical references during interchange."
        ),
        problem=(
            "Studios often lose provenance when assets travel between DCCs and the "
            "farm, which makes debugging mismatched lighting or props expensive."
        ),
        approach=(
            "Store per-asset UUIDs, variant sets, and publish timestamps in a USD "
            "registry layer alongside a compact JSON index.",
            "Expose a read-only client that DCC tooling can query to resolve the "
            "latest approved asset or specific review tags.",
            "Provide a diff utility that surfaces schema or payload changes "
            "between publishes to aid regression investigations.",
        ),
        deliverables=(
            "USD layer schema for registry payloads",
            "Query helper returning resolved prim paths for DCC clients",
            "Diff CLI that reports breaking vs additive changes",
        ),
        dependencies=("USD core", "Studio metadata conventions"),
    ),
    CodexTask(
        slug="pbr-material-bridge",
        title="PBR Material Bridge",
        dcc="Cross-DCC",
        description=(
            "Normalise PBR material parameters so Cinema4D, Nuke, Unreal, and "
            "Anima can share USD lookdev without manual tweaks."
        ),
        problem=(
            "Each DCC interprets roughness, IOR, and displacement scales "
            "differently, forcing artists to rebuild looks for every handoff."
        ),
        approach=(
            "Define a studio PBR profile that maps to Redshift, Arnold/Standard "
            "Surface, Unreal, and OpenUSD Preview Surface parameters.",
            "Bundle LUTs and conversion helpers for textures (metalness, gloss, "
            "normal formats) so incoming assets match the profile.",
            "Ship a validation report that flags noncompliant shaders and suggests "
            "automatic fixes before publish.",
        ),
        deliverables=(
            "Authoritative PBR profile definition and conversions",
            "CLI validator with autofix suggestions",
            "USD material library updated to the shared profile",
        ),
        dependencies=("Material Harmonizer", "USD shading schemas"),
    ),
)


def list_codex_tasks() -> tuple[CodexTask, ...]:
    """Return every codex task defined across DCC integrations."""

    tasks: list[CodexTask] = []
    tasks.extend(CROSS_DCC_CODEX_TASKS)

    from libraries.creative.dcc.cinema4d.codex_tasks import CINEMA4D_CODEX_TASKS
    from libraries.creative.dcc.nuke.codex_tasks import NUKE_CODEX_TASKS
    from libraries.creative.dcc.unreal.codex_tasks import UNREAL_CODEX_TASKS
    from libraries.creative.dcc.anima.codex_tasks import ANIMA_CODEX_TASKS
    from libraries.creative.dcc.deadline.codex_tasks import DEADLINE_CODEX_TASKS

    tasks.extend(CINEMA4D_CODEX_TASKS)
    tasks.extend(NUKE_CODEX_TASKS)
    tasks.extend(UNREAL_CODEX_TASKS)
    tasks.extend(ANIMA_CODEX_TASKS)
    tasks.extend(DEADLINE_CODEX_TASKS)

    return tuple(tasks)


__all__ = [
    "CodexTask",
    "CROSS_DCC_CODEX_TASKS",
    "list_codex_tasks",
]
