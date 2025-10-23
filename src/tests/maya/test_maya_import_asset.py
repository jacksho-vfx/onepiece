from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from libraries.creative.dcc.maya import maya


class DummyPath:
    """Test double that mimics the subset of :class:`pathlib.Path` we rely on."""

    def __init__(self, value: str) -> None:
        self._value = value
        path = Path(value)
        self.name = path.name
        self.suffix = path.suffix

    def exists(self) -> bool:
        return True

    def __str__(self) -> str:
        return self._value


@pytest.mark.parametrize(
    ("filename", "expected_kwargs"),
    (
        ("asset.ma", {"type": "mayaAscii"}),
        ("asset.mb", {"type": "mayaBinary"}),
        ("asset.fbx", {"type": "FBX"}),
        ("asset.usd", {"type": "USD Import"}),
        ("asset.usda", {"type": "USD Import"}),
        ("asset.usdc", {"type": "USD Import"}),
        ("asset.usdz", {"type": "USD Import"}),
    ),
)
def test_import_asset_dispatches_import_type(
    monkeypatch: pytest.MonkeyPatch, filename: str, expected_kwargs: Dict[str, Any]
) -> None:
    """``import_asset`` should pass the correct type flag based on extension."""

    fake_path = DummyPath(f"/project/{filename}")
    captured: Dict[str, Any] = {}

    def _fake_import(path: DummyPath, **kwargs: Any) -> None:
        captured["path"] = path
        captured["kwargs"] = kwargs

    monkeypatch.setattr(maya, "_import", _fake_import)

    maya.import_asset(fake_path)

    assert captured["path"] is fake_path
    assert captured["kwargs"] == expected_kwargs
