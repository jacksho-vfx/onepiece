from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class _FakeAudioContainer:
    def __init__(self) -> None:
        self.streams = SimpleNamespace(audio=[])
        self.closed = False

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


def test_convert_audio_to_mono_raises_when_no_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _FakeAudioContainer()

    def _fake_open(path: str, mode: str | None = None) -> _FakeAudioContainer:
        if mode == "w":  # pragma: no cover - defensive
            pytest.fail("Output container should not be opened when no audio streams exist")
        return container

    monkeypatch.setitem(sys.modules, "av", SimpleNamespace(open=_fake_open))

    sys.modules.pop("libraries.platform.media.manipulations", None)
    manipulations = importlib.import_module("libraries.platform.media.manipulations")

    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "output.wav"
    input_path.write_text("dummy")

    with pytest.raises(ValueError, match="No audio streams"):
        manipulations.convert_audio_to_mono(input_path, output_path)

    assert container.closed is True

    sys.modules.pop("libraries.platform.media.manipulations", None)
