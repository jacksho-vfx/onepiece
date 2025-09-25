"""A very small ShotGrid client abstraction used for the exercises.

The real project contains a far more capable implementation, however wiring it
in would add a large amount of surface area for the tests.  The simplified
version keeps the public API compatible with the behaviour that the unit tests
exercise: looking up and creating projects.
"""

from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, TypedDict

__all__ = ["ShotgridClient"]


class Project(TypedDict):
    """Internal structure used to describe a ShotGrid project."""

    id: int
    name: str


@dataclass
class ProjectStore:
    """In-memory storage used by :class:`ShotgridClient`.

    The storage is deliberately tiny but the abstraction makes it trivial to
    substitute a different backend in the future.
    """

    _projects: MutableMapping[str, Project] = field(default_factory=dict)

    def get(self, name: str) -> Project | None:
        return self._projects.get(name)

    def add(self, project: Project) -> Project:
        self._projects[project["name"]] = project
        return project

    def next_id(self) -> int:
        return len(self._projects) + 1


class Version(TypedDict):
    """Internal structure representing a registered ShotGrid Version."""

    id: int
    code: str
    project: str
    project_id: int
    shot: str
    path: str
    description: str


@dataclass
class VersionStore:
    """In-memory store for :class:`Version` entities."""

    _versions: MutableMapping[int, Version] = field(default_factory=dict)

    def add(self, version: Version) -> Version:
        self._versions[version["id"]] = version
        return version

    def next_id(self) -> int:
        return len(self._versions) + 1

    def list(self) -> List[Version]:
        return list(self._versions.values())


class ShotgridClient:
    """A lightweight facade around a small in-memory project store."""

    def __init__(
        self,
        store: ProjectStore | None = None,
        version_store: VersionStore | None = None,
    ) -> None:
        self._store = store or ProjectStore()
        self._versions = version_store or VersionStore()

    # The following private helpers are patched in the unit tests so they are
    # intentionally minimal.
    def _find_project(self, name: str) -> Project | None:
        """Return the project matching *name* if one exists."""

        return self._store.get(name)

    def _create_project(self, name: str) -> Project:
        """Create a new project entry with a predictable payload."""

        project: Project = {"id": self._store.next_id(), "name": name}
        return self._store.add(project)

    def get_or_create_project(self, name: str) -> Project:
        """Fetch the project called *name* or create it if it doesn't exist."""

        project = self._find_project(name)
        if project is not None:
            return project
        return self._create_project(name)

    # ------------------------------------------------------------------
    # Version helpers
    # ------------------------------------------------------------------
    def register_version(
        self,
        project_name: str,
        shot_code: str,
        file_path: Path,
        description: str | None = None,
    ) -> Version:
        """Register a new Version entry linked to *project_name* and *shot_code*."""

        if not project_name:
            raise ValueError("project_name must be supplied")
        if not shot_code:
            raise ValueError("shot_code must be supplied")

        project = self.get_or_create_project(project_name)
        version: Version = {
            "id": self._versions.next_id(),
            "code": file_path.stem,
            "project": project["name"],
            "project_id": project["id"],
            "shot": shot_code,
            "path": str(file_path),
            "description": description if description else "",
        }
        return self._versions.add(version)

    def list_versions(self) -> List[Version]:
        """Return all stored Version entries."""

        return self._versions.list()
