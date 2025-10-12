"""Default local-disk filepath handler for OnePiece."""

from pathlib import Path
from typing import Optional

import structlog

from libraries.handlers.protocols import FilepathHandlerProtocol

log = structlog.get_logger(__name__)


class FilepathHandler(FilepathHandlerProtocol):  # type: ignore[misc]
    """
    Simple filesystem handler that builds paths under a configurable root.

    Example root:
        /mnt/projects
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self.root = Path(root or "/mnt/projects").resolve()
        log.debug("filepath_handler_init", root=str(self.root))

    # --- Project Level ----------------------------------------------------- #
    def get_project_dir(self, project_name: str) -> Path:
        path = self.root / "projects" / project_name
        return self._ensure(path)

    # --- Episode/Scene/Shot ------------------------------------------------- #
    def get_episode_dir(self, project_name: str, episode: str) -> Path:
        path = self.get_project_dir(project_name) / "episodes" / episode
        return self._ensure(path)

    def get_scene_dir(self, project_name: str, episode: str, scene: str) -> Path:
        path = self.get_episode_dir(project_name, episode) / "scenes" / scene
        return self._ensure(path)

    def get_shot_dir(
        self, project_name: str, episode: str, scene: str, shot: str
    ) -> Path:
        path = self.get_scene_dir(project_name, episode, scene) / "shots" / shot
        return self._ensure(path)

    # --- Media -------------------------------------------------------------- #
    def get_original_media_dir(self, project_name: str) -> Path:
        path = self.get_project_dir(project_name) / "media" / "original"
        return self._ensure(path)

    # --- Utility ------------------------------------------------------------ #
    def _ensure(self, path: Path) -> Path:
        """
        Ensure the directory exists and return it.
        """
        if not path.exists():
            log.info("creating_directory", path=str(path))
            path.mkdir(parents=True, exist_ok=True)
        return path
