"""
ShotGrid xData models for create/search payloads.

These models are designed for input (sending data to ShotGrid),
not for representing full API responses.
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class SGxBase(BaseModel):
    """
    Base class for xData input models.
    Includes a default entity_type to help when building ShotGrid payloads.
    """
    entity_type: str = Field(..., description="ShotGrid entity type")


class ProjectData(SGxBase):
    entity_type: str = Field(default="Project", const=True)
    name: Optional[str] = Field(None, description="Full project name")
    code: Optional[str] = Field(None, description="Short project code")
    extra: Dict[str, Any] = Field(default_factory=dict)


class VersionData(SGxBase):
    entity_type: str = Field(default="Version", const=True)
    code: Optional[str] = None
    description: Optional[str] = None
    project_id: Optional[int] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class EpisodeData(SGxBase):
    entity_type: str = Field(default="Episode", const=True)
    code: Optional[str] = None
    project_id: Optional[int] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class SceneData(SGxBase):
    entity_type: str = Field(default="Scene", const=True)
    code: Optional[str] = None
    project_id: Optional[int] = None
    episode_id: Optional[int] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class ShotData(SGxBase):
    entity_type: str = Field(default="Shot", const=True)
    code: Optional[str] = None
    project_id: Optional[int] = None
    scene_id: Optional[int] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class TaskData(SGxBase):
    entity_type: str = Field(default="Task", const=True)
    content: Optional[str] = None
    project_id: Optional[int] = None
    entity_id: Optional[int] = None
    related_entity_type: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class PlaylistData(SGxBase):
    entity_type: str = Field(default="Playlist", const=True)
    code: Optional[str] = None
    project_id: Optional[int] = None
    version_ids: List[int] = Field(default_factory=list)
    extra: Dict[str, Any] = Field(default_factory=dict)

