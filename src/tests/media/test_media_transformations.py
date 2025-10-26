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


class _FakeProxyVideoFrame:
    def __init__(self, data: str) -> None:
        self.data = data

    @classmethod
    def from_ndarray(cls, array: str, format: str = "rgb24") -> "_FakeProxyVideoFrame":
        return cls(array)

    def reformat(self, width: int, height: int) -> "_FakeProxyVideoFrame":
        return self


class _FakeProxyStream:
    def __init__(self, container: "_FakeProxyContainer") -> None:
        self._container = container
        self.height = 0
        self.width = 0
        self.pix_fmt = ""
        self._flushed = False

    def encode(self, frame: _FakeProxyVideoFrame | None = None):
        if frame is None:
            if self._flushed:
                return []
            self._flushed = True
            return ["flush"]
        return f"packet-{frame.data}"


class _FailingProxyStream(_FakeProxyStream):
    def encode(self, frame: _FakeProxyVideoFrame | None = None):  # type: ignore[override]
        raise RuntimeError("encode error")


class _FakeProxyContainer:
    def __init__(self, path: str, *, fail_encode: bool) -> None:
        self.path = Path(path)
        self._fail_encode = fail_encode
        self.muxed: list[str] = []
        self.closed = False

    def add_stream(self, codec: str, rate: int) -> _FakeProxyStream:
        if self._fail_encode:
            return _FailingProxyStream(self)
        return _FakeProxyStream(self)

    def mux(self, packet: str) -> None:
        self.muxed.append(packet)

    def close(self) -> None:
        self.closed = True
        if self.muxed:
            self.path.write_text("\n".join(self.muxed))


@pytest.fixture()
def install_proxy_modules(monkeypatch: pytest.MonkeyPatch):
    containers: list[_FakeProxyContainer] = []

    def _install(*, fail_encode: bool = False) -> list[_FakeProxyContainer]:
        containers.clear()

        def _open(path: str, mode: str = "r") -> _FakeProxyContainer:
            container = _FakeProxyContainer(path, fail_encode=fail_encode)
            containers.append(container)
            return container

        fake_av = SimpleNamespace(open=_open, VideoFrame=_FakeProxyVideoFrame)

        def _imread(path: str) -> str:
            return Path(path).read_text()

        fake_iio = SimpleNamespace(imread=_imread)

        monkeypatch.setitem(sys.modules, "av", fake_av)
        monkeypatch.setitem(sys.modules, "imageio", SimpleNamespace(v3=fake_iio))
        monkeypatch.setitem(sys.modules, "imageio.v3", fake_iio)

        return containers

    yield _install

    for module in ["av", "imageio", "imageio.v3"]:
        sys.modules.pop(module, None)


def test_convert_mov_to_exrs_exports_first_frame(
    tmp_path: Path, fake_modules: None
) -> None:
    sys.modules.pop("libraries.platform.media.transformations", None)
    transformations = importlib.import_module(
        "libraries.platform.media.transformations"
    )

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


def test_create_proxy_from_exrs_creates_missing_directory(
    tmp_path: Path, install_proxy_modules
) -> None:
    containers = install_proxy_modules()

    exr_dir = tmp_path / "exr"
    exr_dir.mkdir()
    for idx in range(2):
        (exr_dir / f"frame{idx}.exr").write_text(f"data{idx}")

    output_mov = tmp_path / "proxy" / "clip.mov"
    assert not output_mov.parent.exists()

    sys.modules.pop("libraries.platform.media.transformations", None)
    transformations = importlib.import_module(
        "libraries.platform.media.transformations"
    )

    result = transformations.create_1080p_proxy_from_exrs(exr_dir, output_mov, fps=24)

    assert output_mov.parent.exists()
    assert output_mov.read_text().splitlines()[0] == "packet-data0"
    assert containers[0].closed is True
    assert result == output_mov


def test_create_proxy_from_exrs_closes_container_on_error(
    tmp_path: Path, install_proxy_modules
) -> None:
    containers = install_proxy_modules(fail_encode=True)

    exr_dir = tmp_path / "exr"
    exr_dir.mkdir()
    (exr_dir / "frame0.exr").write_text("data0")

    output_mov = tmp_path / "proxy" / "clip.mov"

    sys.modules.pop("libraries.platform.media.transformations", None)
    transformations = importlib.import_module(
        "libraries.platform.media.transformations"
    )

    with pytest.raises(RuntimeError):
        transformations.create_1080p_proxy_from_exrs(exr_dir, output_mov, fps=24)

    assert output_mov.parent.exists()
    assert not output_mov.exists()
    assert containers[0].closed is True
