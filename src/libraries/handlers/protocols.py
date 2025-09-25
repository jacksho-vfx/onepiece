"""Protocols for OnePiece filesystem handlers."""

from typing import Protocol

from upath import UPath


class FilepathHandlerProtocol(Protocol):
    """
    Protocol that all filepath handlers must follow.
    """

    def get_project_dir(self, project_name: str) -> UPath: ...

    def get_episode_dir(self, project_name: str, episode: str) -> UPath: ...

    def get_scene_dir(self, project_name: str, episode: str, scene: str) -> UPath: ...

    def get_shot_dir(
        self, project_name: str, episode: str, scene: str, shot: str
    ) -> UPath: ...

    def get_original_media_dir(self, project_name: str) -> UPath: ...
