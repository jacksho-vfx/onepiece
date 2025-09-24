"""A very small ShotGrid client abstraction used for the exercises.

The real project contains a far more capable implementation, however wiring it
in would add a large amount of surface area for the tests.  The simplified
version keeps the public API compatible with the behaviour that the unit tests
exercise: looking up and creating projects.
"""

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from typing import TypedDict

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


class ShotgridClient:
    """A lightweight facade around a small in-memory project store."""

    def __init__(self, store: ProjectStore | None = None) -> None:
        self._store = store or ProjectStore()

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
