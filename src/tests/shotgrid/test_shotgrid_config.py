from __future__ import annotations

import pytest
from pydantic import ValidationError

from libraries.integrations.shotgrid.config import load_config


def test_load_config_requires_all_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "ONEPIECE_SHOTGRID_URL",
        "ONEPIECE_SHOTGRID_SCRIPT",
        "ONEPIECE_SHOTGRID_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        load_config()


def test_load_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEPIECE_SHOTGRID_URL", "https://example.test")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_SCRIPT", "my-script")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_KEY", "top-secret")

    cfg = load_config()

    assert cfg.base_url == "https://example.test"
    assert cfg.script_name == "my-script"
    assert cfg.api_key == "top-secret"
