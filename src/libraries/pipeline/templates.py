"""Bundled pipeline templates aimed at small studio workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class PipelineTemplate:
    """Container for a reusable pipeline template."""

    name: str
    summary: str
    description: str
    manifest: Mapping[str, Any]


_TEMPLATE_REGISTRY: tuple[PipelineTemplate, ...] = (
    PipelineTemplate(
        name="starter.ingest_review",
        summary="Ingest vendor deliveries and prep a review package.",
        description=(
            "A lightweight ingest pipeline that validates a delivery, pushes media to "
            "storage, and creates a review package. Each step is powered by the built-in "
            "shell step so studios can swap the commands with their local tooling."
        ),
        manifest={
            "name": "starter-ingest-review",
            "summary": "Validate and prepare a delivery for review.",
            "parameters": {
                "delivery_path": {
                    "type": "string",
                    "description": "Path to the incoming delivery root.",
                },
                "project": {
                    "type": "string",
                    "description": "Project or show identifier.",
                },
            },
            "steps": [
                {
                    "id": "validate",
                    "uses": "shell",
                    "with": {
                        "command": "onepiece aws ingest {delivery_path} --project {project} --dry-run",
                        "capture_output": True,
                    },
                },
                {
                    "id": "ingest",
                    "uses": "shell",
                    "with": {
                        "command": "onepiece aws ingest {delivery_path} --project {project} --resume",
                    },
                },
                {
                    "id": "review-package",
                    "uses": "shell",
                    "with": {
                        "command": "onepiece shotgrid package-playlist --project {project}",
                    },
                },
            ],
        },
    ),
    PipelineTemplate(
        name="starter.archvis_publish",
        summary="Publish archvis renders to a review bucket.",
        description=(
            "A minimal archvis pipeline that packages renders, uploads them to object "
            "storage, and posts a notification. Replace the commands with your render "
            "farm uploader or studio-specific tooling."
        ),
        manifest={
            "name": "starter-archvis-publish",
            "summary": "Package archvis renders and ship them to review.",
            "parameters": {
                "render_path": {
                    "type": "string",
                    "description": "Directory that contains the rendered frames.",
                },
                "shot_name": {
                    "type": "string",
                    "description": "Human-friendly identifier for the shot or view.",
                },
                "bucket": {
                    "type": "string",
                    "description": "S3 bucket or storage target for review media.",
                },
            },
            "steps": [
                {
                    "id": "package",
                    "uses": "shell",
                    "with": {
                        "command": "onepiece dcc publish --dcc maya --scene-name {shot_name} --renders {render_path}",
                    },
                },
                {
                    "id": "upload",
                    "uses": "shell",
                    "with": {
                        "command": "onepiece aws sync-to --bucket {bucket} --local-path {render_path}",
                    },
                },
                {
                    "id": "notify",
                    "uses": "noop",
                    "with": {
                        "message": "Notify reviewers via email or chat here.",
                    },
                },
            ],
        },
    ),
)


def list_pipeline_templates() -> Sequence[PipelineTemplate]:
    """Return the available pipeline templates."""

    return _TEMPLATE_REGISTRY


def get_pipeline_template(name: str) -> PipelineTemplate:
    """Return a specific pipeline template by name."""

    normalized = name.strip().lower()
    for template in _TEMPLATE_REGISTRY:
        if template.name.lower() == normalized:
            return template
    available = ", ".join(sorted(template.name for template in _TEMPLATE_REGISTRY))
    raise KeyError(f"Unknown pipeline template '{name}'. Available: {available}.")


__all__ = [
    "PipelineTemplate",
    "get_pipeline_template",
    "list_pipeline_templates",
]
