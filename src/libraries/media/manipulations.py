"""
Manipulations: audio conversion and sequence renumbering using PyAV.
"""

import UPath
import structlog
import av
import shutil

log = structlog.get_logger(__name__)


def convert_audio_to_mono(input_audio: UPath, output_audio: UPath) -> UPath:
    """
    Downmix a stereo audio file to mono using PyAV.
    """
    log.info("convert_audio_to_mono", src=str(input_audio), dst=str(output_audio))

    in_container = av.open(str(input_audio))
    out_container = av.open(str(output_audio), mode="w")

    in_stream = in_container.streams.audio[0]
    out_stream = out_container.add_stream("pcm_s16le", rate=in_stream.rate)
    out_stream.channels = 1

    for frame in in_container.decode(in_stream):
        mono = frame.to_ndarray(layout="mono")  # type: ignore[call-arg]
        out_frame = av.AudioFrame.from_ndarray(mono, layout="mono")
        out_frame.sample_rate = in_stream.rate
        for packet in out_stream.encode(out_frame):
            out_container.mux(packet)

    for packet in out_stream.encode():
        out_container.mux(packet)

    out_container.close()
    in_container.close()
    return output_audio


def renumber_sequence(
    input_dir: UPath,
    pattern: str = "frame.%04d.exr",
    start_number: int = 1001,
) -> None:
    """
    Rename EXR sequence to start at a specified frame number.
    """
    frames = sorted(input_dir.glob("*.exr"))
    if not frames:
        raise FileNotFoundError(f"No EXR files found in {input_dir}")

    for i, frame in enumerate(frames):
        new_num = start_number + i
        new_name = pattern % new_num
        new_path = input_dir / new_name
        log.debug("renumbering", old=str(frame), new=str(new_path))
        shutil.move(str(frame), new_path)
