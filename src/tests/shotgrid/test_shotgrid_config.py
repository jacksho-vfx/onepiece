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


@pytest.mark.parametrize(
    "env_name",
    [
        "SHOTGRID_SCRIPT_NAME",
        "ONEPIECE_SHOTGRID_SCRIPT_NAME",
    ],
)
def test_load_config_supports_script_name_alias(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    monkeypatch.setenv("ONEPIECE_SHOTGRID_URL", "https://example.test")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_KEY", "top-secret")
    for key in (
        "ONEPIECE_SHOTGRID_SCRIPT",
        "SHOTGRID_SCRIPT",
        "script",
        "script_name",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv(env_name, "alias-script")

    cfg = load_config()

    assert cfg.script_name == "alias-script"


@pytest.mark.parametrize(
    "env_name",
    [
        "SHOTGRID_API_KEY",
        "ONEPIECE_SHOTGRID_API_KEY",
    ],
)
def test_load_config_supports_api_key_alias(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    monkeypatch.setenv("ONEPIECE_SHOTGRID_URL", "https://example.test")
    monkeypatch.setenv("ONEPIECE_SHOTGRID_SCRIPT", "my-script")
    for key in (
        "ONEPIECE_SHOTGRID_KEY",
        "SHOTGRID_KEY",
        "api_key",
        "key",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv(env_name, "alias-secret")

    cfg = load_config()

    assert cfg.api_key == "alias-secret"
