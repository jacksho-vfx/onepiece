from types import SimpleNamespace

from src.apps.onepiece.misc import info as info_module


def test_info_masks_shotgrid_key(monkeypatch, capsys):
    monkeypatch.setenv("ONEPIECE_SHOTGRID_KEY", "supersecretkey")

    log_calls: dict[str, object] = {}

    def fake_info(event: str, **kwargs: object) -> None:
        log_calls["event"] = event
        log_calls["kwargs"] = kwargs

    monkeypatch.setattr(info_module, "log", SimpleNamespace(info=fake_info))

    info_module.info()

    captured = capsys.readouterr().out
    expected_masked = info_module.mask_sensitive_value("supersecretkey")

    assert f"ShotGrid Key: {expected_masked}" in captured
    assert log_calls["event"] == "info_report"
    assert log_calls["kwargs"].get("shotgrid_key") == expected_masked


def test_mask_sensitive_value_handles_edge_cases():
    assert info_module.mask_sensitive_value("Not set") == "Not set"
    assert info_module.mask_sensitive_value("") == ""
    assert info_module.mask_sensitive_value("abc", visible_chars=4) == "***"
