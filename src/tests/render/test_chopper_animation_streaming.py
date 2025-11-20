from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from libraries.automation.render.chopper import ChopperRenderError, _write_animation


def test_write_animation_streams_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frame_yields: list[int] = []

    def frame_generator() -> object:
        for idx in range(25):
            frame_yields.append(idx)
            yield object()

    class DummyAnimationWriter:
        def __init__(self, frames: Iterable[object], fps: int):
            assert not isinstance(frames, list)
            self.frames = frames
            self.fps = fps

        def write_mp4(
            self, destination: Path
        ) -> int:  # pragma: no cover - exercised indirectly
            return sum(1 for _ in self.frames)

        def write_gif(self, destination: Path) -> int:
            return sum(1 for _ in self.frames)

    monkeypatch.setattr(
        "libraries.automation.render.chopper.AnimationWriter", DummyAnimationWriter
    )

    written = _write_animation(frame_generator(), tmp_path / "animation.mp4", "mp4", 24)

    assert written == len(frame_yields)
    assert frame_yields == list(range(25))


def test_write_animation_wraps_stream_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def frame_generator() -> object:
        yield object()

    class DummyAnimationWriter:
        def __init__(self, frames: Iterable[object], fps: int):
            self.frames = frames
            self.fps = fps

        def write_mp4(self, destination: Path) -> int:
            raise ValueError("boom")

        def write_gif(self, destination: Path) -> int:  # pragma: no cover - defensive
            raise ValueError("boom")

    monkeypatch.setattr(
        "libraries.automation.render.chopper.AnimationWriter", DummyAnimationWriter
    )

    with pytest.raises(ChopperRenderError):
        _write_animation(frame_generator(), tmp_path / "animation.mp4", "mp4", 24)
