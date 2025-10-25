import os
import json
from types import SimpleNamespace
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from apps.onepiece.misc import info as info_module


def test_info_masks_shotgrid_key(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ONEPIECE_SHOTGRID_KEY", "supersecretkey")

    log_calls: dict[str, Any] = {}

    def fake_info(event: str, **kwargs: Any) -> None:
        log_calls["event"] = event
        log_calls["kwargs"] = kwargs

    monkeypatch.setattr(info_module, "log", SimpleNamespace(info=fake_info))

    info_module.info()

    captured = capsys.readouterr().out
    expected_masked = info_module.mask_sensitive_value("supersecretkey")

    assert f"ShotGrid Key: {expected_masked}" in captured
    assert log_calls["event"] == "info_report"
    assert isinstance(log_calls["kwargs"], dict)
    assert log_calls["kwargs"].get("shotgrid_key") == expected_masked


def test_info_supports_json_format(
    monkeypatch: MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ONEPIECE_SHOTGRID_KEY", "supersecretkey")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_URL", "https://shotgrid.example")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_SCRIPT", "luffy")
    monkeypatch.setenv("AWS_PROFILE", "straw-hat")

    monkeypatch.setattr(info_module.metadata, "version", lambda _: "9.9.9")
    monkeypatch.setattr(info_module, "detect_installed_dccs", lambda: ["Maya"])

    info_module.info(output_format="json")

    captured = capsys.readouterr().out
    payload = json.loads(captured)

    assert payload["onepiece_version"] == "9.9.9"
    assert payload["shotgrid"]["key"].endswith("tkey")
    assert payload["aws_profile"] == "straw-hat"
    assert payload["detected_dccs"] == ["Maya"]


def test_mask_sensitive_value_handles_edge_cases() -> None:
    assert info_module.mask_sensitive_value("Not set") == "Not set"
    assert info_module.mask_sensitive_value("") == ""
    assert info_module.mask_sensitive_value("abc", visible_chars=4) == "***"


def test_detect_installed_dccs_avoids_false_positive(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", os.pathsep.join(["/Users/Mayank/bin"]))
    monkeypatch.setattr(info_module.shutil, "which", lambda command: None)

    assert info_module.detect_installed_dccs() == ["None detected"]


def test_detect_installed_dccs_detects_available(monkeypatch: MonkeyPatch) -> None:
    def fake_which(command: str) -> str | None:
        if command in {"maya", "maya.exe"}:
            return "/opt/autodesk/maya"
        return None

    monkeypatch.setattr(info_module.shutil, "which", fake_which)

    assert info_module.detect_installed_dccs() == ["Maya"]
