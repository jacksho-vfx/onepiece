"""
Transformations: convert and create proxy media using PyAV.
"""

from pathlib import Path

import UPath
import av
import structlog

log = structlog.get_logger(__name__)


def create_1080p_proxy_from_exrs(
    exr_sequence_dir: UPath,
    output_mov: Path,
    fps: int = 24,
) -> UPath:
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

    container = av.open(str(output_mov), mode="w")
    stream = container.add_stream("h264", rate=fps)
    stream.height = 1080
    stream.width = 1920
    stream.pix_fmt = "yuv420p"

    for frame_path in pattern:
        img = iio.imread(frame_path)
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        frame = frame.reformat(width=1920, height=1080)
        packet = stream.encode(frame)
        if packet:
            container.mux(packet)

    for packet in stream.encode():
        container.mux(packet)
    container.close()

    return output_mov


def convert_mov_to_exrs(
    mov_path: UPath,
    output_dir: UPath,
    fps: int = 24,
    start_number: int = 1001,
) -> UPath:
    """
    Convert a MOV to an EXR sequence using PyAV and imageio.
    """
    import imageio.v3 as iio

    output_dir.mkdir(parents=True, exist_ok=True)

    container = av.open(str(mov_path))
    video_stream = container.streams.video[0]

    frame_number = start_number
    for frame in container.decode(video_stream):
        if frame_number % int(video_stream.rate * (1 / fps)) == 0:
            img = frame.to_ndarray(format="rgb24")
            out_path = output_dir / f"frame.{frame_number:04d}.exr"
            iio.imwrite(out_path, img)
        frame_number += 1

    container.close()
    return output_dir
