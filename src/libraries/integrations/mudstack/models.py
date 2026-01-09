"""Mudstack data models mirroring the ShotGrid helper style."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MudstackEntity(BaseModel):
    """Base class for Mudstack input payloads."""

    resource: str = Field(..., description="API resource used when building requests")

    def to_payload(self) -> Dict[str, Any]:
        """Return a serialisable payload excluding helper-only attributes."""

        return self.model_dump(exclude={"resource"}, exclude_none=True)


class ProjectData(MudstackEntity):
    resource: str = "projects"
    name: str = Field(..., description="Human readable project name")
    code: Optional[str] = Field(None, description="Short code used for quick filters")
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AssetData(MudstackEntity):
    resource: str = "assets"
    name: str = Field(..., description="Asset or shot name")
    project_id: Optional[str] = Field(None, description="Owning project identifier")
    asset_type: Optional[str] = Field(None, description="Type or category in Mudstack")
    status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskData(MudstackEntity):
    resource: str = "tasks"
    name: str = Field(..., description="Task name or code")
    project_id: Optional[str] = None
    asset_id: Optional[str] = Field(None, description="Related asset identifier")
    assignee: Optional[str] = None
    status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReviewSessionData(MudstackEntity):
    resource: str = "reviews"
    name: str = Field(..., description="Review session name")
    project_id: Optional[str] = None
    version_ids: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
