"""Protocols for OnePiece filesystem handlers."""

from pathlib import Path
from typing import Protocol


class FilepathHandlerProtocol(Protocol):
    """
    Protocol that all filepath handlers must follow.
    """

    def get_project_dir(self, project_name: str) -> Path: ...

    def get_episode_dir(self, project_name: str, episode: str) -> Path: ...

    def get_sequence_dir(
        self, project_name: str, episode: str, sequence: str
    ) -> Path: ...

    def get_scene_dir(self, project_name: str, episode: str, scene: str) -> Path: ...

    def get_shot_dir(
        self, project_name: str, episode: str, scene: str, shot: str
    ) -> Path: ...

    def get_original_media_dir(self, project_name: str) -> Path: ...
