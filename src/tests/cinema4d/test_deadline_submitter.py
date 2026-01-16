from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

import pytest

from libraries.creative.dcc.cinema4d.deadline_submitter import (
    DeadlineSubmitterDialog,
    build_default_settings,
)


class RecordingDialog:
    def __init__(self) -> None:
        self.title: str | None = None
        self.strings: dict[int, str] = {}
        self.ints: dict[int, int] = {}
        self.bools: dict[int, bool] = {}
        self.hidden: dict[int, bool] = {}
        self.buttons: list[int] = []
        self.open_calls: list[dict[str, Any]] = []

    def SetTitle(self, title: str) -> None:
        self.title = title

    def AddStaticText(self, element_id: int, *_args: Any) -> None:
        self.hidden.setdefault(element_id, False)

    def AddEditText(self, element_id: int, *_args: Any) -> None:
        self.strings.setdefault(element_id, "")

    def AddCheckbox(self, element_id: int, *_args: Any) -> None:
        self.bools.setdefault(element_id, False)

    def AddButton(self, element_id: int, *_args: Any) -> None:
        self.buttons.append(element_id)

    def SetString(self, element_id: int, value: str) -> None:
        self.strings[element_id] = value

    def GetString(self, element_id: int) -> str:
        return self.strings.get(element_id, "")

    def SetInt32(self, element_id: int, value: int) -> None:
        self.ints[element_id] = value

    def GetInt32(self, element_id: int) -> int:
        return self.ints.get(element_id, 0)

    def SetBool(self, element_id: int, value: bool) -> None:
        self.bools[element_id] = value

    def HideElement(self, element_id: int, hidden: bool) -> None:
        self.hidden[element_id] = hidden

    def CreateLayout(self) -> bool:
        return True

    def Open(
        self, dlgtype: int, *, pluginid: int, defaultw: int, defaulth: int
    ) -> bool:
        self.open_calls.append(
            {
                "dlgtype": dlgtype,
                "pluginid": pluginid,
                "defaultw": defaultw,
                "defaulth": defaulth,
            }
        )
        self.CreateLayout()  # type: ignore[misc]
        return True

    def Command(self, _button_id: int, _msg: object | None) -> bool:
        return False


class RecordingGuiModule:
    messages: list[str] = []
    GeDialog = RecordingDialog

    @staticmethod
    def MessageDialog(message: str) -> None:
        RecordingGuiModule.messages.append(message)


class FakeDocument:
    def __init__(self, path: Path) -> None:
        self._path = path

    def GetDocumentPath(self) -> str:
        return str(self._path.parent)

    def GetDocumentName(self) -> str:
        return self._path.name


class FakeDocuments:
    def __init__(self, path: Path) -> None:
        self._path = path

    def GetActiveDocument(self) -> FakeDocument:
        return FakeDocument(self._path)


class FakeCinema4DModule:
    DLG_TYPE_ASYNC = 1
    gui = RecordingGuiModule

    def __init__(self, path: Path) -> None:
        self.documents = FakeDocuments(path)


@pytest.fixture(autouse=True)
def reset_messages() -> Iterator[None]:
    RecordingGuiModule.messages = []
    yield
    RecordingGuiModule.messages = []


def test_deadline_submitter_builds_defaults_from_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"frame_range": [101, 110]}), encoding="utf-8")
    monkeypatch.setenv("ONEPIECE_CINEMA4D_SUMMARY", str(summary))
    monkeypatch.setenv("RENDER_DEADLINE_PRIORITY", "65")
    monkeypatch.setenv("RENDER_DEADLINE_CHUNK_SIZE", "8")
    monkeypatch.setenv("RENDER_DEADLINE_POOL", "primary")

    capabilities = {
        "default_priority": 50,
        "default_chunk_size": 4,
        "chunk_size_enabled": True,
    }
    scene_path = tmp_path / "scene.c4d"
    fake_module = FakeCinema4DModule(scene_path)

    defaults = build_default_settings(
        module=fake_module,
        env=dict(os.environ),
        capabilities=capabilities,
    )

    assert defaults.scene == str(scene_path)
    assert defaults.frames == "101-110"
    assert defaults.output.endswith("scene_render")
    assert defaults.priority == 65
    assert defaults.chunk_size == 8
    assert defaults.pool == "primary"


def test_deadline_submitter_hides_advanced_until_toggled(tmp_path: Path) -> None:
    fake_module = FakeCinema4DModule(tmp_path / "scene.c4d")
    dialog = DeadlineSubmitterDialog(
        module=fake_module,
        capabilities={"chunk_size_enabled": True},
    )

    dialog.open()

    assert dialog._dialog.hidden[dialog.ID_CHUNK_SIZE] is True
    assert dialog._dialog.hidden[dialog.ID_POOL] is True

    dialog.Command(dialog.ID_ADVANCED_TOGGLE, None)

    assert dialog._dialog.hidden[dialog.ID_CHUNK_SIZE] is False
    assert dialog._dialog.hidden[dialog.ID_POOL] is False


def test_deadline_submitter_submits_with_overrides(tmp_path: Path) -> None:
    fake_module = FakeCinema4DModule(tmp_path / "scene.c4d")
    submitted: dict[str, Any] = {}

    def fake_submit_job(**kwargs: Any) -> dict[str, Any]:
        submitted.update(kwargs)
        return {"job_id": "job-1", "status": "queued", "farm_type": "deadline"}

    dialog = DeadlineSubmitterDialog(
        module=fake_module,
        capabilities={"chunk_size_enabled": True},
        submit_job=fake_submit_job,
    )

    ui = dialog.open()
    ui.SetString(dialog.ID_FRAME_RANGE, "5-20")
    ui.SetString(dialog.ID_OUTPUT_PATH, "/tmp/output")
    ui.SetInt32(dialog.ID_PRIORITY, 55)
    ui.SetString(dialog.ID_USER, "sanji")
    dialog.Command(dialog.ID_ADVANCED_TOGGLE, None)
    ui.SetInt32(dialog.ID_CHUNK_SIZE, 4)
    ui.SetString(dialog.ID_POOL, "queue-a")

    dialog.Command(dialog.ID_SUBMIT_BUTTON, None)

    assert submitted["frames"] == "5-20"
    assert submitted["output"] == "/tmp/output"
    assert submitted["priority"] == 55
    assert submitted["user"] == "sanji"
    assert submitted["chunk_size"] == 4
    assert submitted["pool"] == "queue-a"
    assert RecordingGuiModule.messages[-1].startswith("Submitted to Deadline")
