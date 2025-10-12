"""
Transformations: convert and create proxy media using PyAV.
"""

from pathlib import Path

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:  # pragma: no cover - only evaluated by type checkers
    import av as _av_module

log = structlog.get_logger(__name__)


def _load_av() -> "_av_module":
    """Import :mod:`av` lazily to keep it optional."""

    try:
        import av  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError(
            "PyAV is required for media transformations. Install the 'av' package."
        ) from exc

    return av


def create_1080p_proxy_from_exrs(
    exr_sequence_dir: Path,
    output_mov: Path,
    fps: int = 24,
) -> Path:
    """
    Create a 1080p H.264 MOV proxy from an EXR image sequence.

    NOTE: PyAV can read/write individual images, but for EXR sequences
    we simply iterate and encode each frame.
    """
    import imageio.v3 as iio

    pattern = sorted(exr_sequence_dir.glob("*.exr"))
    if not pattern:
        raise FileNotFoundError(f"No EXR files found in {exr_sequence_dir}")

    log.info("creating_proxy", frames=len(pattern), output=str(output_mov))

    av = _load_av()

    container = av.open(str(output_mov), mode="w")
    stream = container.add_stream("h264", rate=fps)
    stream.height = 1080
    stream.width = 1920
    stream.pix_fmt = "yuv420p"

    for frame_path in pattern:
        img = iio.imread(str(frame_path))
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        frame = frame.reformat(width=1920, height=1080)
        packet = stream.encode(frame)
        if packet:
            container.mux(packet)

    for packet in stream.encode():  # type: ignore[assignment]
        container.mux(packet)
    container.close()

    return output_mov


def convert_mov_to_exrs(
    mov_path: Path,
    output_dir: Path,
    fps: int = 24,
    start_number: int = 1001,
) -> Path:
    """
    Convert a MOV to an EXR sequence using PyAV and imageio.
    """
    import imageio.v3 as iio

    output_dir.mkdir(parents=True, exist_ok=True)

    av = _load_av()

    container = av.open(str(mov_path))
    video_stream = container.streams.video[0]

    source_rate = getattr(video_stream, "average_rate", None) or video_stream.rate
    try:
        source_rate_value = float(source_rate)
    except (TypeError, ValueError):  # pragma: no cover - defensive fallback
        source_rate_value = float(fps)

    frame_interval = max(int(round(source_rate_value / float(fps))), 1)

    frame_number = start_number
    frame_index = 0
    for frame in container.decode(video_stream):
        if frame_index % frame_interval == 0:
            img = frame.to_ndarray(format="rgb24")
            out_path = output_dir / f"frame.{frame_number:04d}.exr"
            iio.imwrite(str(out_path), img)
            frame_number += 1
        frame_index += 1

    container.close()
    return output_dir
