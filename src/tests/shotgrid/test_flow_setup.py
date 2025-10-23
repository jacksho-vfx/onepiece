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
#     with pytest.raises(RuntimeError, match="ShotGrid project 'my-show' was not found"):
#         setup_single_shot("my-show", "E01_S01_SH010", client=client)
#
#
# def test_setup_single_shot_missing_project_id() -> None:
#     """A project without an ``id`` should raise before accessing the hierarchy."""
#
#     client = _FakeShotGridClient(project={"name": "my-show"})
#
#     with pytest.raises(
#         RuntimeError, match="ShotGrid project 'my-show' is missing an id"
#     ):
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
#     assert client.episode_payload.project_id == 777  # type: ignore[attr-defined]
#     assert client.scene_payload.project_id == 777  # type: ignore[attr-defined]
#     assert client.shot_payload.project_id == 777  # type: ignore[attr-defined]
#     assert client.scene_payload.code == "E01_S01"  # type: ignore[attr-defined]
#
#
# def test_setup_single_shot_supports_hyphenated_codes() -> None:
#     """Hyphen separated shot codes should be normalised like underscore codes."""
#
#     client = _FakeShotGridClient(project={"id": 888, "name": "my-show"})
#
#     setup_single_shot("my-show", "E02-S03-SH020", client=client)
#
#     assert client.episode_payload.code == "E02"  # type: ignore[attr-defined]
#     assert client.scene_payload.code == "E02_S03"  # type: ignore[attr-defined]
#     assert client.shot_payload.code == "E02-S03-SH020"  # type: ignore[attr-defined]
