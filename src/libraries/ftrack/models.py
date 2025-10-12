from __future__ import annotations

"""Typed pydantic models that mirror common Ftrack entities."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FtrackModel(BaseModel):
    """Base class for all Ftrack data models."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class FtrackProject(FtrackModel):
    """Representation of a project as returned by the Ftrack REST API."""

    id: str = Field(..., description="Unique identifier assigned by Ftrack")
    name: str = Field(..., description="Short code or slug of the project")
    full_name: str | None = Field(
        default=None, description="Human readable name displayed in the UI"
    )
    status: str | None = Field(
        default=None, description="Pipeline status or lifecycle flag"
    )
    custom_attributes: dict[str, Any] | None = Field(
        default=None, description="Raw custom attributes returned by the API"
    )


class FtrackShot(FtrackModel):
    """Representation of a shot entity."""

    id: str = Field(..., description="Identifier of the shot")
    name: str = Field(..., description="Name/code of the shot")
    project_id: str = Field(..., description="Owning project identifier")
    sequence: str | None = Field(
        default=None, description="Parent sequence/episode name when available"
    )
    status: str | None = Field(default=None, description="Shot status as string")
    task_ids: list[str] = Field(
        default_factory=list, description="Identifiers of tasks linked to the shot"
    )


class FtrackTask(FtrackModel):
    """Representation of a task record."""

    id: str = Field(..., description="Task identifier")
    name: str = Field(..., description="Display name of the task")
    status: str | None = Field(default=None, description="Current task status")
    assignee: str | None = Field(
        default=None, description="Display name of the assigned user if any"
    )
    shot_id: str | None = Field(
        default=None,
        alias="parent_id",
        description="Identifier of the parent shot or asset",
    )
    task_type: str | None = Field(
        default=None, description="Pipeline step or schema of the task"
    )
