from __future__ import annotations

from types import SimpleNamespace

import pytest

from apps.onepiece.render.submit import helpers
from apps.onepiece.render.submit.helpers import resolve_metrics


def test_resolve_metrics_honors_cli_metrics_without_optimization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_profile_load(*_: object, **__: object) -> None:
        pytest.fail("load_profile should not be called when optimize is False")

    monkeypatch.setattr(helpers, "load_profile", _fail_profile_load)

    metrics, sources = resolve_metrics(
        optimize=False,
        profile_name="manual",
        queue_depth=42,
        average_frame_ms=16.5,
    )

    assert metrics.queue_depth == 42
    assert metrics.average_frame_time_ms == 16.5
    assert sources == ("cli.queue_depth", "cli.average_frame_ms")


def test_resolve_metrics_merges_profile_and_cli_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_profile_load(*_: object, **__: object) -> SimpleNamespace:
        return SimpleNamespace(
            data={
                "render": {
                    "optimization": {
                        "queue_depth": 100,
                        "average_frame_ms": 25.0,
                    }
                }
            }
        )

    monkeypatch.setattr(helpers, "load_profile", _fake_profile_load)

    metrics, sources = resolve_metrics(
        optimize=True,
        profile_name="profile",
        queue_depth=80,
        average_frame_ms=12.5,
    )

    assert metrics.queue_depth == 80
    assert metrics.average_frame_time_ms == 12.5
    assert sources == ("profile", "cli.queue_depth", "cli.average_frame_ms")
