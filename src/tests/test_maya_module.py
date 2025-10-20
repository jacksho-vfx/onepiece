from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest


def test_maya_module_errors_without_required_pymel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "libraries.dcc.maya.maya"

    # Ensure a clean import state for the maya module.
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.delitem(sys.modules, "libraries.dcc.maya", raising=False)

    stub_pymel = ModuleType("pymel")
    stub_core = ModuleType("pymel.core")
    stub_pymel.core = stub_core  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pymel", stub_pymel)
    monkeypatch.setitem(sys.modules, "pymel.core", stub_core)

    with pytest.raises(RuntimeError, match="listReferences"):
        importlib.import_module(module_name)

    # ``import_module`` caches failed imports, ensure they are cleared for later tests.
    monkeypatch.delitem(sys.modules, module_name, raising=False)
