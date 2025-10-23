# """Tests for :mod:`libraries.integrations.shotgrid.flow_setup`."""
#
# from __future__ import annotations
#
# from typing import Any
#
# import pytest
#
# from libraries.integrations.shotgrid.flow_setup import setup_single_shot
#
#
# class _FakeShotGridClient:
#     """Minimal stub mirroring the methods used by ``setup_single_shot``."""
#
#     def __init__(self, project: Any) -> None:
#         self._project = project
#         self.episode_payload = None
#         self.scene_payload = None
#         self.shot_payload = None
#
#     def get_project(
#         self, name: str
#     ) -> Any:  # pragma: no cover - behaviour tested via setup
#         return self._project
#
#     def get_or_create_project(self, payload: Any, template: str | None) -> Any:
#         return self._project
#
#     def get_project_id_by_name(self, payload: Any) -> Any:
#         self._project = payload
#         return 123
#
#     def get_or_create_episode(self, payload: Any) -> Any:
#         self.episode_payload = payload
#         return {"id": 101}
#
#     def get_or_create_scene(self, payload: Any) -> Any:
#         self.scene_payload = payload
#         return {"id": 202}
#
#     def get_or_create_shot(self, payload: Any) -> Any:
#         self.shot_payload = payload
#         return {"id": 303}
#
#
# def test_setup_single_shot_missing_project() -> None:
#     """A missing project should raise a descriptive error."""
#
#     client = _FakeShotGridClient(project=None)
#
#     with pytest.raises(RuntimeError, match="Project 'my-show' could not be retrieved or created"):
#         setup_single_shot("my-show", "E01_S01_SH010", client=client)
#
#
# def test_setup_single_shot_uses_project_id() -> None:
#     """Ensure the resolved project id is propagated to downstream calls."""
#
#     client = _FakeShotGridClient(project={"id": 777, "name": "my-show"})
#
#     setup_single_shot("my-show", "E01_S01_SH010", client=client)
#
#     assert client.episode_payload.project_id == 123  # type: ignore[attr-defined]
#     assert client.scene_payload.project_id == 123  # type: ignore[attr-defined]
#     assert client.shot_payload.project_id == 123  # type: ignore[attr-defined]
