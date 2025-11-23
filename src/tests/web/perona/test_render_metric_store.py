from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from apps.perona.web.dashboard.dependencies import RenderMetricStore


def test_store_rotates_when_threshold_is_exceeded(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.ndjson"
    store = RenderMetricStore(metrics_path, max_bytes=120, max_files=3)

    first_payload = [{"payload": "x" * 80}]
    second_payload = [{"payload": "y" * 80}]

    store.persist(first_payload)
    store.persist(second_payload)

    rotated = Path(f"{metrics_path}.1")
    assert rotated.exists()

    with metrics_path.open(encoding="utf-8") as handle:
        active_lines = [json.loads(line) for line in handle.read().splitlines()]
    with rotated.open(encoding="utf-8") as handle:
        rotated_lines = [json.loads(line) for line in handle.read().splitlines()]

    assert [entry["payload"] for entry in active_lines] == ["y" * 80]
    assert [entry["payload"] for entry in rotated_lines] == ["x" * 80]


def test_store_honours_retention_limit(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.ndjson"
    store = RenderMetricStore(metrics_path, max_bytes=100, max_files=2)

    for idx in range(3):
        store.persist([{"payload": f"batch-{idx}", "body": "z" * 60}])

    assert metrics_path.exists()
    assert Path(f"{metrics_path}.1").exists()
    assert not Path(f"{metrics_path}.2").exists()

    with metrics_path.open(encoding="utf-8") as handle:
        active_payloads = [
            json.loads(line)["payload"] for line in handle.read().splitlines()
        ]
    with Path(f"{metrics_path}.1").open(encoding="utf-8") as handle:
        rolled_payloads = [
            json.loads(line)["payload"] for line in handle.read().splitlines()
        ]

    assert active_payloads == ["batch-2"]
    assert rolled_payloads == ["batch-1"]


def test_concurrent_writes_respect_rotation(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.ndjson"
    store = RenderMetricStore(metrics_path, max_bytes=500, max_files=3)

    payloads = [
        [{"payload": f"worker-{worker}-item-{item}", "body": "v" * 80}]
        for worker in range(4)
        for item in range(3)
    ]

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(store.persist, payloads))

    seen_payloads: list[str] = []
    for candidate in [
        metrics_path,
        Path(f"{metrics_path}.1"),
        Path(f"{metrics_path}.2"),
    ]:
        if not candidate.exists():
            continue
        with candidate.open(encoding="utf-8") as handle:
            seen_payloads.extend(
                json.loads(line)["payload"] for line in handle.read().splitlines()
            )

    assert len(seen_payloads) == len(payloads)
    assert set(seen_payloads) == {
        f"worker-{worker}-item-{item}" for worker in range(4) for item in range(3)
    }
