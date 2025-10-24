"""Tests for the Perona machine learning helper module."""

from __future__ import annotations

from libraries.analytics.perona.ml_foundations import (
    Dataset,
    FeatureImportance,
    MLFeature,
    TrainingExample,
    analyse_cost_relationships,
    compute_feature_statistics,
    recommend_best_practices,
)


def build_example(renders: float, revisions: float, cost: float) -> TrainingExample:
    return TrainingExample(
        feature_values={"renders": renders, "revisions": revisions},
        cost=cost,
    )


def test_dataset_to_matrix_and_targets_apply_transforms() -> None:
    dataset = Dataset(
        [
            build_example(10, 1, 200),
            build_example(8, 2, 180),
            build_example(12, 0, 220),
        ]
    )
    features = [
        MLFeature("renders", "Number of renders", transform=lambda value: value / 10),
        MLFeature("revisions", "Number of revisions"),
    ]

    matrix = dataset.to_matrix(features)
    targets = dataset.to_targets()

    assert matrix == [
        [1.0, 1.0],
        [0.8, 2.0],
        [1.2, 0.0],
    ]
    assert targets == [200.0, 180.0, 220.0]


def test_dataset_split_respects_ratio_and_shuffle() -> None:
    dataset = Dataset(
        [
            build_example(10, 1, 200),
            build_example(8, 2, 180),
            build_example(12, 0, 220),
            build_example(9, 3, 210),
        ]
    )

    train, test = dataset.split(train_ratio=0.5, shuffle=True, seed=42)

    assert len(train) == 2
    assert len(test) == 2
    # Deterministic shuffle ensures consistent order across runs.
    assert train.to_targets() != test.to_targets()


def test_compute_feature_statistics_reports_expected_values() -> None:
    dataset = Dataset(
        [
            build_example(10, 1, 200),
            build_example(8, 2, 180),
            build_example(12, 0, 220),
        ]
    )

    stats = compute_feature_statistics(dataset)

    renders_stats = next(stat for stat in stats if stat.name == "renders")
    revisions_stats = next(stat for stat in stats if stat.name == "revisions")

    assert round(renders_stats.mean, 2) == 10.0
    assert round(renders_stats.stddev, 3) == 1.633
    assert renders_stats.minimum == 8
    assert renders_stats.maximum == 12

    assert round(revisions_stats.mean, 2) == 1.0
    assert round(revisions_stats.stddev, 3) == 0.816


def test_recommendations_capture_relationship_trends() -> None:
    dataset = Dataset(
        [
            build_example(10, 1, 200),
            build_example(8, 2, 180),
            build_example(12, 0, 220),
            build_example(6, 3, 160),
        ]
    )

    importances = analyse_cost_relationships(dataset)
    recommendations = recommend_best_practices(importances, top_n=2)

    assert isinstance(importances[0], FeatureImportance)
    assert any("Reduce renders" in message for message in recommendations)
    assert any("Monitor revisions" in message or "Consider investing" in message for message in recommendations)

