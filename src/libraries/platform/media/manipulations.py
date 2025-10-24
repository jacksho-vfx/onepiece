"""
Manipulations: audio conversion and sequence renumbering using PyAV.
"""

from pathlib import Path
import uuid

import structlog
import av
import shutil

log = structlog.get_logger(__name__)


def convert_audio_to_mono(input_audio: Path, output_audio: Path) -> Path:
    """
    Downmix a stereo audio file to mono using PyAV.
    """
    log.info("convert_audio_to_mono", src=str(input_audio), dst=str(output_audio))

    output_audio.parent.mkdir(parents=True, exist_ok=True)

    with av.open(str(input_audio)) as in_container:
        audio_streams = in_container.streams.audio
        if not audio_streams:
            raise ValueError(
                f"No audio streams found in input file '{input_audio}'. "
                "Cannot convert to mono."
            )

        in_stream = audio_streams[0]

        with av.open(str(output_audio), mode="w") as out_container:
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
    return output_audio


def renumber_sequence(
    input_dir: Path,
    pattern: str = "frame.%04d.exr",
    start_number: int = 1001,
) -> None:
    """
    Rename EXR sequence to start at a specified frame number.
    """
    frames = sorted(input_dir.glob("*.exr"))
    if not frames:
        raise FileNotFoundError(f"No EXR files found in {input_dir}")

    temp_moves: list[tuple[Path, Path]] = []
    temp_prefix = f".renumber_tmp_{uuid.uuid4().hex}"

    for i, frame in enumerate(frames):
        new_num = start_number + i
        new_name = pattern % new_num
        new_path = input_dir / new_name

        if frame == new_path:
            log.debug("renumbering", old=str(frame), new=str(new_path))
            continue

        temp_path = input_dir / f"{temp_prefix}_{i}{frame.suffix}"
        log.debug("renumbering_stage", old=str(frame), temp=str(temp_path))
        shutil.move(str(frame), temp_path)
        temp_moves.append((temp_path, new_path))

    for temp_path, new_path in temp_moves:
        if new_path.exists():
            log.debug("renumbering_overwrite", target=str(new_path))
            new_path.unlink()

        log.debug("renumbering_finalize", temp=str(temp_path), new=str(new_path))
        shutil.move(str(temp_path), new_path)
