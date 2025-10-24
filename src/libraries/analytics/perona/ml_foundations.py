"""Utilities that support machine learning style cost analysis for Perona.

The module focuses on the plumbing that analytics experiments need before a
proper machine learning model is introduced.  It provides a set of
lightweight abstractions for working with training data, computing summary
statistics and surfacing best-practice recommendations based on simple linear
relationships.  The goal is to give data scientists a repeatable baseline so
they can iterate on actual model experimentation without rewriting the same
glue code for every project.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from statistics import mean
from typing import Callable, Iterable, Mapping, MutableSequence, Sequence


FeatureTransform = Callable[[float], float]


@dataclass(frozen=True)
class MLFeature:
    """Describe an input feature that feeds into a cost model."""

    name: str
    description: str
    unit: str | None = None
    is_cost_driver: bool = True
    transform: FeatureTransform | None = None

    def apply(self, value: float) -> float:
        """Return ``value`` after applying the optional transformation."""

        if self.transform is None:
            return value
        return self.transform(value)


@dataclass(frozen=True)
class TrainingExample:
    """Represents a single labelled observation for the model."""

    feature_values: Mapping[str, float]
    cost: float

    def __post_init__(self) -> None:  # pragma: no cover - `dataclasses` hook
        normalised = {name: float(value) for name, value in self.feature_values.items()}
        if not normalised:
            msg = "TrainingExample requires at least one feature value"
            raise ValueError(msg)
        object.__setattr__(self, "feature_values", normalised)
        object.__setattr__(self, "cost", float(self.cost))


class Dataset(Sequence[TrainingExample]):
    """A small convenience wrapper around a sequence of ``TrainingExample``."""

    def __init__(self, examples: Iterable[TrainingExample]):
        self._examples = tuple(examples)
        if not self._examples:
            msg = "Dataset requires at least one training example"
            raise ValueError(msg)
        feature_names = {
            feature for example in self._examples for feature in example.feature_values
        }
        self._feature_names = tuple(sorted(feature_names))

    def __len__(self) -> int:
        return len(self._examples)

    def __getitem__(self, index: int) -> TrainingExample:
        return self._examples[index]

    @property
    def feature_names(self) -> tuple[str, ...]:
        """Return the sorted collection of feature names observed in the set."""

        return self._feature_names

    def to_matrix(
        self,
        features: Sequence[MLFeature] | None = None,
        *,
        fill_value: float = 0.0,
    ) -> list[list[float]]:
        """Return a dense feature matrix that respects the requested order.

        Missing values are replaced with ``fill_value`` so downstream code can
        immediately consume the matrix using ``numpy``/``pandas`` without
        additional imputation.  If ``features`` is ``None`` the observed feature
        names are used and no transformation is performed.
        """

        if features is None:
            return [
                [example.feature_values.get(name, fill_value) for name in self._feature_names]
                for example in self._examples
            ]

        observed = {name for name in self._feature_names}
        requested = {feature.name for feature in features}
        if not requested.issubset(observed):
            missing = ", ".join(sorted(requested - observed))
            msg = f"Dataset is missing values for requested features: {missing}"
            raise KeyError(msg)

        return [
            [
                feature.apply(example.feature_values.get(feature.name, fill_value))
                for feature in features
            ]
            for example in self._examples
        ]

    def to_targets(self) -> list[float]:
        """Return the target cost values for the dataset."""

        return [example.cost for example in self._examples]

    def split(
        self,
        *,
        train_ratio: float = 0.8,
        shuffle: bool = False,
        seed: int | None = None,
    ) -> tuple[Dataset, Dataset]:
        """Split the dataset into train/test sets while respecting order.

        The ``train_ratio`` must be in the ``(0, 1)`` range.  Both splits are
        guaranteed to contain at least one example; if that is not possible the
        method raises ``ValueError``.
        """

        if not 0 < train_ratio < 1:
            msg = "train_ratio must be between 0 and 1"
            raise ValueError(msg)

        indices = list(range(len(self._examples)))
        if shuffle:
            rng = random.Random(seed)
            rng.shuffle(indices)

        split_index = int(math.floor(len(indices) * train_ratio))
        split_index = max(1, min(split_index, len(indices) - 1))

        def build(idx: MutableSequence[int]) -> Dataset:
            return Dataset(self._examples[i] for i in idx)

        train = build(indices[:split_index])
        test = build(indices[split_index:])
        return train, test


@dataclass(frozen=True)
class FeatureStatistics:
    """Summary statistics for a single feature."""

    name: str
    mean: float
    stddev: float
    minimum: float
    maximum: float


def compute_feature_statistics(dataset: Dataset) -> tuple[FeatureStatistics, ...]:
    """Compute descriptive statistics for each observed feature."""

    stats: list[FeatureStatistics] = []
    for name in dataset.feature_names:
        values = [example.feature_values.get(name, 0.0) for example in dataset]
        feature_mean = mean(values)
        variance = mean((value - feature_mean) ** 2 for value in values)
        stats.append(
            FeatureStatistics(
                name=name,
                mean=feature_mean,
                stddev=math.sqrt(variance),
                minimum=min(values),
                maximum=max(values),
            )
        )
    return tuple(stats)


@dataclass(frozen=True)
class FeatureImportance:
    """Represents the strength of the linear relationship with the cost."""

    name: str
    slope: float
    correlation: float

    @property
    def trend(self) -> str:
        if math.isclose(self.slope, 0.0):
            return "neutral"
        return "increasing" if self.slope > 0 else "decreasing"


def analyse_cost_relationships(dataset: Dataset) -> tuple[FeatureImportance, ...]:
    """Estimate linear relationships between each feature and cost."""

    targets = dataset.to_targets()
    target_mean = mean(targets)
    target_variance = mean((target - target_mean) ** 2 for target in targets)
    target_std = math.sqrt(target_variance)
    importances: list[FeatureImportance] = []

    for name in dataset.feature_names:
        values = [example.feature_values.get(name, 0.0) for example in dataset]
        value_mean = mean(values)
        covariance = mean(
            (value - value_mean) * (target - target_mean)
            for value, target in zip(values, targets)
        )
        variance = mean((value - value_mean) ** 2 for value in values)
        if math.isclose(variance, 0.0):
            slope = 0.0
            correlation = 0.0
        else:
            slope = covariance / variance
            value_std = math.sqrt(variance)
            if math.isclose(value_std, 0.0) or math.isclose(target_std, 0.0):
                correlation = 0.0
            else:
                correlation = covariance / (value_std * target_std)
        importances.append(
            FeatureImportance(name=name, slope=slope, correlation=correlation)
        )

    return tuple(sorted(importances, key=lambda item: abs(item.slope), reverse=True))


def recommend_best_practices(
    importances: Sequence[FeatureImportance], *, top_n: int = 3
) -> tuple[str, ...]:
    """Convert feature importances into practitioner friendly messages."""

    recommendations: list[str] = []
    for importance in importances[:top_n]:
        trend = importance.trend
        if trend == "neutral":
            recommendations.append(
                f"Monitor {importance.name} – its relationship to cost is currently neutral."
            )
        elif trend == "increasing":
            recommendations.append(
                f"Reduce {importance.name} where possible; each unit increases cost by "
                f"approximately {importance.slope:.2f}."
            )
        else:
            recommendations.append(
                f"Consider investing more in {importance.name}; each unit is associated with "
                f"a cost reduction of roughly {abs(importance.slope):.2f}."
            )
    return tuple(recommendations)


__all__ = [
    "Dataset",
    "FeatureImportance",
    "FeatureStatistics",
    "MLFeature",
    "TrainingExample",
    "analyse_cost_relationships",
    "compute_feature_statistics",
    "recommend_best_practices",
]

