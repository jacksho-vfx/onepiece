"""Tests for the Cinema 4D custom command panel."""

from __future__ import annotations

import pytest

from libraries.creative.dcc.cinema4d.panel import CommandPanel, register_cleanup_command


class FakeGeDialog:
    def __init__(self) -> None:
        self.title: str | None = None
        self.buttons: list[tuple[int, int, int, int, str]] = []
        self.tooltips: dict[int, str] = {}
        self.open_calls: list[dict[str, int]] = []
        self.layout_created = False

    def SetTitle(self, title: str) -> None:
        self.title = title

    def AddButton(
        self, button_id: int, flags: int, initw: int, inith: int, label: str
    ) -> None:
        self.buttons.append((button_id, flags, initw, inith, label))

    def SetTooltip(self, button_id: int, tooltip: str) -> None:
        self.tooltips[button_id] = tooltip

    def CreateLayout(self) -> bool:
        self.layout_created = True
        return True

    def Open(
        self, dlgtype: int, *, pluginid: int = 0, defaultw: int = 0, defaulth: int = 0
    ) -> bool:
        self.open_calls.append(
            {
                "dlgtype": dlgtype,
                "pluginid": pluginid,
                "defaultw": defaultw,
                "defaulth": defaulth,
            }
        )
        self.CreateLayout()
        return True

    def Command(self, button_id: int, msg: object | None) -> bool:
        return False


class FakeGuiModule:
    GeDialog = FakeGeDialog
    messages: list[str] = []

    @staticmethod
    def MessageDialog(message: str) -> None:
        FakeGuiModule.messages.append(message)


class FakeCinema4DModule:
    gui = FakeGuiModule
    DLG_TYPE_ASYNC = 1
    DLG_TYPE_MODAL = 2
    BFH_SCALEFIT = 4


def test_panel_requires_cinema4d(monkeypatch: pytest.MonkeyPatch) -> None:
    from libraries.creative.dcc.cinema4d import panel as panel_module

    monkeypatch.setattr(panel_module, "c4d", None)

    with pytest.raises(RuntimeError, match="Cinema 4D Python API is unavailable"):
        CommandPanel()


def test_panel_opens_and_dispatches_commands() -> None:
    panel = CommandPanel(title="Custom Commands", module=FakeCinema4DModule)

    triggered: list[str] = []

    panel.register_command(
        "Say Hello", lambda: triggered.append("hello"), "Greets the user"
    )

    dialog = panel.show()

    assert isinstance(dialog, FakeGeDialog)
    assert dialog.open_calls == [
        {
            "dlgtype": FakeCinema4DModule.DLG_TYPE_ASYNC,
            "pluginid": panel.PANEL_ID,
            "defaultw": 400,
            "defaulth": 0,
        }
    ]
    assert dialog.title == "Custom Commands"
    assert dialog.layout_created is True
    button_id, *_ = dialog.buttons[0]
    assert dialog.tooltips[button_id] == "Greets the user"

    dialog.Command(button_id, None)
    assert triggered == ["hello"]


def test_panel_registers_commands_after_show() -> None:
    panel = CommandPanel(module=FakeCinema4DModule)

    panel.register_command("Initial", lambda: None)
    dialog = panel.show()
    assert len(dialog.buttons) == 1

    new_triggered = []
    panel.register_command("Secondary", lambda: new_triggered.append("triggered"))
    assert len(dialog.buttons) == 2

    second_button_id, *_ = dialog.buttons[1]
    dialog.Command(second_button_id, None)
    assert new_triggered == ["triggered"]


def test_panel_supports_modal_open() -> None:
    panel = CommandPanel(module=FakeCinema4DModule)
    dialog = panel.show(async_open=False, width=320, height=200)

    assert dialog.open_calls[-1] == {
        "dlgtype": FakeCinema4DModule.DLG_TYPE_MODAL,
        "pluginid": panel.PANEL_ID,
        "defaultw": 320,
        "defaulth": 200,
    }


def test_register_cleanup_command_runs_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from libraries.creative.dcc.cinema4d import panel as panel_module

    FakeGuiModule.messages = []
    panel = CommandPanel(module=FakeCinema4DModule)

    expected_stats = {
        "removed_materials": 3,
        "removed_empty_nulls": 2,
        "removed_hidden_singletons": 1,
        "removed_layers": 4,
    }

    def fake_cleanup_scene(**kwargs: object) -> dict[str, int]:
        assert kwargs == {"module": FakeCinema4DModule}
        return expected_stats

    monkeypatch.setattr(panel_module, "cleanup_scene", fake_cleanup_scene)
    register_cleanup_command(panel, module=FakeCinema4DModule)

    dialog = panel.show()
    button_id, *_ = dialog.buttons[-1]
    dialog.Command(button_id, None)

    assert FakeGuiModule.messages == [
        "Removed 3 materials, 2 nulls, 1 hidden objects, 4 layers."
    ]
