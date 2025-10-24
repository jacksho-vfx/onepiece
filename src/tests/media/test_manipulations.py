from __future__ import annotations

import importlib
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Generator

import pytest


class _FakeAudioContainer:
    def __init__(self) -> None:
        self.streams = SimpleNamespace(audio=[])
        self.closed = False

    def __enter__(self) -> "_FakeAudioContainer":  # pragma: no cover - trivial
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:  # pragma: no cover - trivial
        self.close()

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True


def test_convert_audio_to_mono_raises_when_no_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = _FakeAudioContainer()

    def _fake_open(path: str, mode: str | None = None) -> _FakeAudioContainer:
        if mode == "w":  # pragma: no cover - defensive
            pytest.fail(
                "Output container should not be opened when no audio streams exist"
            )
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


class _FakeDecodingFrame:
    def to_ndarray(self, *, layout: str) -> list[Any]:  # pragma: no cover - trivial
        return [layout]


class _FakeInputContainer:
    def __init__(self) -> None:
        self.streams = SimpleNamespace(audio=[SimpleNamespace(rate=48000)])
        self.closed = False

    def __enter__(self) -> "_FakeInputContainer":  # pragma: no cover - trivial
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:  # pragma: no cover - trivial
        self.close()

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True

    def decode(
        self, stream: object
    ) -> Generator[_FakeDecodingFrame, Any, None]:  # pragma: no cover - defensive
        yield _FakeDecodingFrame()


class _FakeOutputStream:
    def __init__(self) -> None:
        self.channels = 0

    def encode(
        self, frame: object | None = None
    ) -> RuntimeError | list[None]:  # pragma: no cover - defensive
        if frame is None:
            return []
        raise RuntimeError("boom")


class _FakeOutputContainer:
    def __init__(self) -> None:
        self.closed = False
        self.stream = _FakeOutputStream()

    def __enter__(self) -> "_FakeOutputContainer":  # pragma: no cover - trivial
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> None:  # pragma: no cover - trivial
        self.close()

    def close(self) -> None:  # pragma: no cover - trivial
        self.closed = True

    def add_stream(
        self, codec: str, *, rate: int
    ) -> _FakeOutputStream:  # pragma: no cover - defensive
        return self.stream

    def mux(self, packet: object) -> None:  # pragma: no cover - defensive
        pass


class _FakeAudioFrame:
    @classmethod
    def from_ndarray(cls, array: list[int], *, layout: str) -> "_FakeAudioFrame":
        frame = cls()
        frame.array = array  # type: ignore[attr-defined]
        frame.layout = layout  # type: ignore[attr-defined]
        frame.sample_rate = 0  # type: ignore[attr-defined]
        return frame


def test_convert_audio_to_mono_recreates_directory_and_closes_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "input.wav"
    output_path = tmp_path / "nested" / "output.wav"

    # Ensure the destination directory does not exist before conversion.
    output_dir = output_path.parent
    output_dir.mkdir(parents=True)
    shutil.rmtree(output_dir)

    input_path.write_text("dummy")

    in_container = _FakeInputContainer()
    out_container = _FakeOutputContainer()

    def _fake_open(path: str, mode: str | None = None) -> object:
        return out_container if mode == "w" else in_container

    fake_av = SimpleNamespace(open=_fake_open, AudioFrame=_FakeAudioFrame)
    monkeypatch.setitem(sys.modules, "av", fake_av)

    sys.modules.pop("libraries.platform.media.manipulations", None)
    manipulations = importlib.import_module("libraries.platform.media.manipulations")

    with pytest.raises(RuntimeError, match="boom"):
        manipulations.convert_audio_to_mono(input_path, output_path)

    assert in_container.closed is True
    assert out_container.closed is True
    assert output_dir.exists()

    sys.modules.pop("libraries.platform.media.manipulations", None)
