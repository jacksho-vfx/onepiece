"""Statistical helpers for analysing render telemetry."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Protocol, Sequence, SupportsFloat, runtime_checkable


@runtime_checkable
class FrameTimeSample(Protocol):
    """Protocol describing telemetry samples with frame timing information."""

    sequence: str
    shot_id: str
    frame_time_ms: SupportsFloat


@runtime_checkable
class ShotRenderSummary(Protocol):
    """Protocol describing summary telemetry for rendered frame counts."""

    sequence: str
    shot_id: str
    frames_rendered: int


def average_frame_time_by_sequence(
    samples: Iterable[FrameTimeSample],
) -> dict[str, float]:
    """Return the mean frame time per sequence.

    Parameters
    ----------
    samples:
        Iterable of telemetry samples containing sequence identifiers and
        ``frame_time_ms`` values.

    Returns
    -------
    dict[str, float]
        Mapping of sequence identifier to the arithmetic mean of the sample
        frame times. Sequences without any samples are omitted from the
        result.
    """

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)

    for sample in samples:
        sequence = sample.sequence
        totals[sequence] += float(sample.frame_time_ms)
        counts[sequence] += 1

    return {
        sequence: totals[sequence] / counts[sequence]
        for sequence in totals
        if counts[sequence]
    }


def average_frame_time_by_shot(
    samples: Iterable[FrameTimeSample],
) -> dict[tuple[str, str], float]:
    """Return the mean frame time for each shot.

    The returned mapping uses ``(sequence, shot_id)`` tuples as keys to ensure
    uniqueness when the same shot identifiers appear across different
    sequences.
    """

    totals: dict[tuple[str, str], float] = defaultdict(float)
    counts: dict[tuple[str, str], int] = defaultdict(int)

    for sample in samples:
        key = (sample.sequence, sample.shot_id)
        totals[key] += float(sample.frame_time_ms)
        counts[key] += 1

    return {key: totals[key] / counts[key] for key in totals if counts[key]}


def rolling_mean(
    values: Sequence[SupportsFloat], window: int
) -> tuple[float | None, ...]:
    """Compute a simple rolling mean across ``values``.

    The returned tuple matches the length of ``values``. Positions before the
    rolling window has enough samples are populated with ``None`` to keep the
    alignment explicit.
    """

    if window <= 0:
        raise ValueError("window must be a positive integer")

    if not values:
        return ()

    data = [float(value) for value in values]
    result: list[float | None] = []
    total = 0.0

    for index, value in enumerate(data):
        total += value
        if index >= window:
            total -= data[index - window]
        if index + 1 >= window:
            result.append(total / window)
        else:
            result.append(None)

    return tuple(result)

def cost_per_frame(
    *,
    gpu_time: SupportsFloat,
    rate_gpu: SupportsFloat,
    cpu_time: SupportsFloat,
    rate_cpu: SupportsFloat,
    storage: SupportsFloat,
    rate_storage: SupportsFloat,
) -> float:
    """Compute the monetary cost of rendering a single frame.

    Parameters
    ----------
    gpu_time:
        GPU render time for the frame, typically in hours.
    rate_gpu:
        Hourly rate charged for GPU usage.
    cpu_time:
        CPU render time for the frame, typically in hours.
    rate_cpu:
        Hourly rate charged for CPU usage.
    storage:
        Storage consumed by the frame, typically in gigabytes.
    rate_storage:
        Cost per unit of storage consumed.
    """

    gpu_time_value = float(gpu_time)
    rate_gpu_value = float(rate_gpu)
    cpu_time_value = float(cpu_time)
    rate_cpu_value = float(rate_cpu)
    storage_value = float(storage)
    rate_storage_value = float(rate_storage)

    for name, value in (
        ("gpu_time", gpu_time_value),
        ("rate_gpu", rate_gpu_value),
        ("cpu_time", cpu_time_value),
        ("rate_cpu", rate_cpu_value),
        ("storage", storage_value),
        ("rate_storage", rate_storage_value),
    ):
        if value < 0:
            raise ValueError(f"{name} cannot be negative")

    return (
        gpu_time_value * rate_gpu_value
        + cpu_time_value * rate_cpu_value
        + storage_value * rate_storage_value
    )


def total_cost_per_shot(
    summaries: Iterable[ShotRenderSummary],
    *,
    cost_per_frame: SupportsFloat,
) -> dict[tuple[str, str], float]:
    """Return the total render cost accrued for each shot.

    Parameters
    ----------
    summaries:
        Iterable of render summaries providing ``frames_rendered`` counts.
    cost_per_frame:
        Monetary cost of rendering a single frame. The same rate is applied to
        every summary provided.
    """

    rate = float(cost_per_frame)
    if rate < 0:
        raise ValueError("cost_per_frame cannot be negative")

    totals: dict[tuple[str, str], float] = defaultdict(float)

    for summary in summaries:
        frames = int(summary.frames_rendered)
        if frames < 0:
            raise ValueError("frames_rendered cannot be negative")
        key = (summary.sequence, summary.shot_id)
        totals[key] += frames * rate

    return {key: round(value, 2) for key, value in totals.items()}


def total_cost_per_sequence(
    summaries: Iterable[ShotRenderSummary],
    *,
    cost_per_frame: SupportsFloat,
) -> dict[str, float]:
    """Aggregate render costs per sequence using ``frames_rendered`` counts."""

    rate = float(cost_per_frame)
    if rate < 0:
        raise ValueError("cost_per_frame cannot be negative")

    totals: dict[str, float] = defaultdict(float)

    for summary in summaries:
        frames = int(summary.frames_rendered)
        if frames < 0:
            raise ValueError("frames_rendered cannot be negative")
        totals[summary.sequence] += frames * rate

    return {sequence: round(value, 2) for sequence, value in totals.items()}


__all__ = [
    "cost_per_frame",
    "average_frame_time_by_sequence",
    "average_frame_time_by_shot",
    "rolling_mean",
    "total_cost_per_shot",
    "total_cost_per_sequence",
]
