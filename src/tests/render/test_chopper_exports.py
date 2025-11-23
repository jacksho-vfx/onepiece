from pathlib import Path

from libraries.automation.render import chopper


def test_normalize_export_format_accepts_exr(tmp_path: Path) -> None:
    destination = tmp_path / "output.exr"

    assert (
        chopper._normalize_export_format(
            output_path=destination, export_format="png", export_was_explicit=False
        )
        == "exr"
    )


def test_write_frames_uses_exr_writer(tmp_path: Path) -> None:
    called: list[tuple[str, Path, str | None, set[str] | None]] = []

    class DummyFrame:
        def __init__(self) -> None:
            self.index = 1

        def save_exr(
            self, destination: Path, *, bit_depth: str, layers: set[str] | None
        ) -> None:
            called.append(("exr", destination, bit_depth, layers))

    frame = DummyFrame()
    written = chopper._write_frames(
        [frame], tmp_path, "exr", bit_depth="float32", layers={"beauty"}
    )

    assert written == 1
    assert called == [("exr", tmp_path / "frame_0001.exr", "float32", {"beauty"})]


def test_write_frames_uses_dpx_writer(tmp_path: Path) -> None:
    called: list[tuple[str, Path, str | None, set[str] | None]] = []

    class DummyFrame:
        def __init__(self) -> None:
            self.index = 3

        def save_dpx(
            self, destination: Path, *, bit_depth: str, layers: set[str] | None
        ) -> None:
            called.append(("dpx", destination, bit_depth, layers))

    frame = DummyFrame()
    written = chopper._write_frames(
        [frame], tmp_path, "dpx", bit_depth="half", layers=None
    )

    assert written == 1
    assert called == [("dpx", tmp_path / "frame_0003.dpx", "half", None)]
