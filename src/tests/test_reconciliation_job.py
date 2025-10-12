from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import pytest
from hypothesis import given, strategies as st

from libraries.reconcile.job import ReconciliationJob
from libraries.reconcile.rules import (
    ExactMatchRule,
    FuzzyMatchRule,
    ToleranceRule,
    build_rules,
    load_rules,
)


@dataclass
class StaticProvider:
    name: str
    payload: Sequence[dict[str, Any]]

    def load(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self.payload]


def test_reconciliation_job_generates_summary(tmp_path: Path) -> None:
    delivery = StaticProvider(
        name="delivery",
        payload=[
            {"shot": "ep001", "name": "Alpha", "frames": 100},
            {"shot": "ep002", "name": "Beta", "frames": 90},
        ],
    )
    source_a = StaticProvider(
        name="filesystem",
        payload=[
            {"shot": "ep001", "name": "Alpha", "frames": 99},
        ],
    )
    source_b = StaticProvider(
        name="vendor",
        payload=[
            {"shot": "ep001", "name": "Alfa", "frames": 100},
            {"shot": "ep002", "name": "Gamma", "frames": 85},
        ],
    )

    rules = [
        ExactMatchRule("shot"),
        FuzzyMatchRule("name", threshold=0.8, weight=2.0),
        ToleranceRule("frames", tolerance=5),
    ]

    job = ReconciliationJob(
        delivery_provider=delivery,
        source_providers=[source_a, source_b],
        rules=rules,
        key_field="shot",
        minimum_score=0.75,
    )

    result = job.run()

    assert result.summary.total_deliveries == 2
    assert result.summary.matched_deliveries == 1
    assert result.summary.unmatched_deliveries == 1
    assert result.summary.matched_percentage == pytest.approx(50.0)
    assert sorted(result.unmatched_delivery_keys) == ["ep002"]

    first_match = result.matches[0]
    assert first_match.fully_matched is True
    vendor_result = next(
        item for item in first_match.sources if item.provider == "vendor"
    )
    assert vendor_result.matched is True
    assert vendor_result.score and vendor_result.score > 0.8
    assert any(diff.field == "name" for diff in vendor_result.differences)
    assert vendor_result.rule_trace

    second_match = result.matches[1]
    assert second_match.fully_matched is False
    vendor_second = next(
        item for item in second_match.sources if item.provider == "vendor"
    )
    assert vendor_second.matched is False
    assert vendor_second.score is not None and vendor_second.score < 0.75

    fs_metrics = next(
        metric
        for metric in result.summary.provider_metrics
        if metric.provider == "filesystem"
    )
    assert fs_metrics.total_records == 1
    assert fs_metrics.matched_records == 1
    assert fs_metrics.unmatched_records == 0

    vendor_metrics = next(
        metric
        for metric in result.summary.provider_metrics
        if metric.provider == "vendor"
    )
    assert vendor_metrics.total_records == 2
    assert vendor_metrics.matched_records == 1
    assert vendor_metrics.unmatched_records == 1

    config_path = tmp_path / "rules.yaml"
    config_path.write_text(
        "rules:\n  - type: exact\n    field: shot\n  - type: tolerance\n    field: frames\n    tolerance: 2\n",
        encoding="utf-8",
    )
    loaded = load_rules(config_path)
    assert len(loaded) == 2


record_strategy = st.lists(
    st.builds(
        lambda shot, name, frames: {"shot": shot, "name": name, "frames": frames},
        shot=st.text(min_size=1, max_size=6).filter(str.strip),
        name=st.text(min_size=1, max_size=6).filter(str.strip),
        frames=st.integers(min_value=1, max_value=1000),
    ),
    max_size=8,
    unique_by=lambda record: record["shot"],
)


@given(record_strategy)
def test_round_trip_consistency(records: list[dict[str, Any]]) -> None:
    delivery = StaticProvider(name="delivery", payload=records)
    source = StaticProvider(name="source", payload=records)

    job = ReconciliationJob(
        delivery_provider=delivery,
        source_providers=[source],
        rules=[ExactMatchRule("shot")],
        key_field="shot",
        minimum_score=1.0,
    )

    result = job.run()

    assert result.summary.total_deliveries == len(records)
    assert result.summary.unmatched_deliveries == 0
    assert not result.unmatched_delivery_keys
    assert all(match.fully_matched for match in result.matches)
    assert all(
        not provider_match.differences
        for match in result.matches
        for provider_match in match.sources
    )


def test_build_rules_from_dict() -> None:
    rules = build_rules(
        [
            {"type": "exact", "field": "shot"},
            {"type": "fuzzy", "field": "name", "threshold": 0.9},
            {"type": "tolerance", "field": "frames", "tolerance": 3},
        ]
    )
    assert len(rules) == 3
    assert isinstance(rules[0], ExactMatchRule)
    assert isinstance(rules[1], FuzzyMatchRule)
    assert isinstance(rules[2], ToleranceRule)
