from __future__ import annotations

import importlib
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Generator

import pytest


class _FakeFrame:
    def __init__(self, label: str) -> None:
        self._label = label

    def to_ndarray(self, format: str = "rgb24") -> str:  # pragma: no cover - trivial
        return self._label


class _FakeVideoStream:
    def __init__(self, *, average_rate: Fraction) -> None:
        self.average_rate = average_rate
        self.rate = average_rate


class _FakeContainer:
    def __init__(self, frames: list[_FakeFrame], stream: _FakeVideoStream) -> None:
        self._frames = frames
        self.streams = SimpleNamespace(video=[stream])

    def decode(
        self, stream: _FakeVideoStream
    ) -> Generator[_FakeFrame, None, None]:  # pragma: no cover - trivial generator
        yield from self._frames

    def close(self) -> None:  # pragma: no cover - trivial
        pass


@pytest.fixture()
def fake_modules(monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[misc]
    def _fake_imwrite(path: str, data: str) -> None:
        dest = Path(path)
        dest.write_text(data)

    frames = [_FakeFrame("f0"), _FakeFrame("f1"), _FakeFrame("f2"), _FakeFrame("f3")]
    stream = _FakeVideoStream(average_rate=Fraction(24000, 1001))
    container = _FakeContainer(frames, stream)

    fake_av = SimpleNamespace(open=lambda *args, **kwargs: container)
    fake_iio = SimpleNamespace(imwrite=_fake_imwrite)

    monkeypatch.setitem(sys.modules, "av", fake_av)
    monkeypatch.setitem(sys.modules, "imageio", SimpleNamespace(v3=fake_iio))
    monkeypatch.setitem(sys.modules, "imageio.v3", fake_iio)

    yield

    for module in ["av", "imageio", "imageio.v3"]:
        sys.modules.pop(module, None)


def test_convert_mov_to_exrs_exports_first_frame(
    tmp_path: Path, fake_modules: None
) -> None:
    sys.modules.pop("libraries.platform.media.transformations", None)
    transformations = importlib.import_module("libraries.platform.media.transformations")

    output_dir = tmp_path / "exr"
    mov_path = tmp_path / "clip.mov"
    mov_path.write_text("dummy")

    result = transformations.convert_mov_to_exrs(
        mov_path,
        output_dir,
        fps=12,
        start_number=1001,
    )

    written_paths = sorted(output_dir.glob("*.exr"))
    assert [path.name for path in written_paths] == ["frame.1001.exr", "frame.1002.exr"]
    assert result == output_dir
