from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

import sys
import types

sys.modules.setdefault("requests", types.ModuleType("requests"))
try:
    import libraries.integrations.ftrack  # noqa: F401  # ensure real module if present
except ModuleNotFoundError:  # pragma: no cover - optional dependency guard
    sys.modules.setdefault(
        "libraries.integrations.ftrack",
        types.ModuleType("libraries.integrations.ftrack"),
    )

from libraries.creative.dcc.maya.character_selector import (  # noqa: E402 - imported after stubs
    CharacterSelectorPanel,
    RigDescriptor,
    discover_rigs,
)


@dataclass
class _FakeNode:
    name_value: str
    attrs: dict[str, Any]

    def name(self) -> str:
        return self.name_value

    def hasAttr(self, attr: str) -> bool:  # noqa: N802 - mimic PyMEL API
        return attr in self.attrs

    def getAttr(self, attr: str) -> Any:  # noqa: N802 - mimic PyMEL API
        return self.attrs[attr]


class _FakePyMel:
    def __init__(self, nodes: List[_FakeNode]):
        self._nodes = nodes
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def ls(self, *args: Any, **kwargs: Any) -> List[_FakeNode]:
        self.calls.append((args, kwargs))
        return list(self._nodes)


class _FakeCmds:
    def __init__(self) -> None:
        self.selections: list[str] = []

    def select(self, target: str, replace: bool = False) -> None:
        if replace:
            self.selections = [target]
        else:
            self.selections.append(target)


def test_discover_rigs_uses_attribute_flag() -> None:
    nodes = [
        _FakeNode("heroA_Rig", {"isCharacterRig": True}),
        _FakeNode("prop01_geo", {"isCharacterRig": False}),
    ]
    fake_pm = _FakePyMel(nodes)

    rigs = discover_rigs(pm=fake_pm)

    assert [rig.name for rig in rigs] == ["heroA_Rig"]
    assert fake_pm.calls == [(tuple(), {"assemblies": True})]


def test_discover_rigs_falls_back_to_name_suffix() -> None:
    nodes = [
        _FakeNode("villain:Body_RIG", {}),
        _FakeNode("environment_grp", {}),
    ]
    fake_pm = _FakePyMel(nodes)

    rigs = discover_rigs(pm=fake_pm)

    assert [rig.name for rig in rigs] == ["villain:Body_RIG"]


def test_character_selector_panel_selects_filtered_rig() -> None:
    nodes = [
        _FakeNode("heroA_Rig", {"isCharacterRig": True}),
        _FakeNode("villain_Rig", {"isCharacterRig": True}),
    ]
    fake_pm = _FakePyMel(nodes)
    fake_cmds = _FakeCmds()

    panel = CharacterSelectorPanel(pm=fake_pm, cmds=fake_cmds)
    panel.refresh()

    filtered = panel.apply_filter("villain")
    assert [rig.name for rig in filtered] == ["villain_Rig"]

    actions = panel.build_selection_actions()
    assert len(actions) == 1
    actions[0]()

    assert fake_cmds.selections == ["villain_Rig"]


def test_rig_descriptor_selection_target_accepts_plain_strings() -> None:
    rig = RigDescriptor(name="testRig", node="plainString")
    assert rig.selection_target() == "plainString"
