"""Rule system used by :mod:`libraries.reconcile.job`."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import yaml
from pydantic import BaseModel, Field, ValidationError


class RuleEvaluation(BaseModel):
    """Result of applying a rule to a pair of records."""

    rule: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(gt=0.0)
    details: str | None = None


class MatchRule:
    """Base class for matching rules.

    Rules evaluate a delivery record against a candidate source record and
    return a :class:`RuleEvaluation`.  Individual rules may restrict the set of
    providers they apply to by populating :attr:`applies_to`.
    """

    def __init__(
        self,
        *,
        name: str | None = None,
        applies_to: Sequence[str] | None = None,
        weight: float = 1.0,
    ) -> None:
        if weight <= 0:
            msg = "rule weight must be greater than zero"
            raise ValueError(msg)
        self.name = name or self.__class__.__name__
        self.applies_to = frozenset(applies_to or ())
        self.weight = weight

    def applicable(self, provider: str) -> bool:
        if not self.applies_to:
            return True
        return provider in self.applies_to

    def evaluate(
        self,
        delivery: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        provider: str,
    ) -> RuleEvaluation:
        """Evaluate the rule for the given delivery/source pair."""

        result = self._evaluate(delivery, candidate, provider=provider)
        return RuleEvaluation(
            rule=self.name,
            passed=result.passed,
            score=result.score,
            weight=self.weight,
            details=result.details,
        )

    @dataclass(slots=True)
    class Result:
        passed: bool
        score: float
        details: str | None = None

    def _evaluate(
        self,
        delivery: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        provider: str,
    ) -> Result:
        raise NotImplementedError


class ExactMatchRule(MatchRule):
    """Match when values for *field* are identical."""

    def __init__(
        self,
        field: str,
        *,
        name: str | None = None,
        applies_to: Sequence[str] | None = None,
        weight: float = 1.0,
    ) -> None:
        super().__init__(name=name, applies_to=applies_to, weight=weight)
        self.field = field

    def _evaluate(
        self,
        delivery: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        provider: str,
    ) -> MatchRule.Result:
        lhs = delivery.get(self.field)
        rhs = candidate.get(self.field)
        passed = lhs == rhs and lhs is not None
        return MatchRule.Result(
            passed=passed,
            score=1.0 if passed else 0.0,
            details=None if passed else f"{self.field!r} mismatch",
        )


class FuzzyMatchRule(MatchRule):
    """Match using :class:`difflib.SequenceMatcher` ratios."""

    def __init__(
        self,
        field: str,
        *,
        threshold: float = 0.75,
        name: str | None = None,
        applies_to: Sequence[str] | None = None,
        weight: float = 1.0,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            msg = "threshold must be between 0.0 and 1.0"
            raise ValueError(msg)
        super().__init__(name=name, applies_to=applies_to, weight=weight)
        self.field = field
        self.threshold = threshold

    def _evaluate(
        self,
        delivery: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        provider: str,
    ) -> MatchRule.Result:
        lhs = delivery.get(self.field)
        rhs = candidate.get(self.field)
        if lhs is None or rhs is None:
            return MatchRule.Result(
                passed=False,
                score=0.0,
                details=f"{self.field!r} missing for fuzzy match",
            )
        ratio = SequenceMatcher(None, str(lhs), str(rhs)).ratio()
        return MatchRule.Result(
            passed=ratio >= self.threshold,
            score=ratio,
            details=None if ratio >= self.threshold else f"ratio {ratio:.2f} < {self.threshold}",
        )


class ToleranceRule(MatchRule):
    """Numeric tolerance based matching rule."""

    def __init__(
        self,
        field: str,
        *,
        tolerance: float,
        name: str | None = None,
        applies_to: Sequence[str] | None = None,
        weight: float = 1.0,
    ) -> None:
        if tolerance < 0:
            msg = "tolerance must be non-negative"
            raise ValueError(msg)
        super().__init__(name=name, applies_to=applies_to, weight=weight)
        self.field = field
        self.tolerance = tolerance

    def _evaluate(
        self,
        delivery: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        provider: str,
    ) -> MatchRule.Result:
        lhs = delivery.get(self.field)
        rhs = candidate.get(self.field)
        try:
            lhs_value = float(lhs)
            rhs_value = float(rhs)
        except (TypeError, ValueError):
            return MatchRule.Result(
                passed=False,
                score=0.0,
                details=f"{self.field!r} not numeric",
            )

        delta = abs(lhs_value - rhs_value)
        passed = delta <= self.tolerance
        if self.tolerance == 0:
            score = 1.0 if passed else 0.0
        else:
            score = max(0.0, 1.0 - min(delta / self.tolerance, 1.0))
        return MatchRule.Result(
            passed=passed,
            score=score,
            details=None if passed else f"delta {delta:.2f} > tolerance {self.tolerance}",
        )


class RuleConfig(BaseModel):
    """Pydantic schema describing rule configuration."""

    type: str
    field: str
    threshold: float | None = None
    tolerance: float | None = None
    name: str | None = None
    applies_to: Sequence[str] | None = None
    weight: float = 1.0


def _instantiate_rule(config: RuleConfig) -> MatchRule:
    rule_type = config.type.lower()
    kwargs: MutableMapping[str, Any] = {
        "name": config.name,
        "applies_to": config.applies_to,
        "weight": config.weight,
    }

    if rule_type in {"exact", "key"}:
        return ExactMatchRule(config.field, **kwargs)
    if rule_type in {"fuzzy", "sequence"}:
        threshold = config.threshold if config.threshold is not None else 0.75
        return FuzzyMatchRule(config.field, threshold=threshold, **kwargs)
    if rule_type in {"tolerance", "numeric"}:
        if config.tolerance is None:
            msg = f"tolerance rule requires tolerance value for field {config.field!r}"
            raise ValueError(msg)
        return ToleranceRule(config.field, tolerance=config.tolerance, **kwargs)

    msg = f"unknown rule type: {config.type}"
    raise ValueError(msg)


def build_rules(configs: Iterable[Mapping[str, Any] | RuleConfig]) -> list[MatchRule]:
    """Create rule instances from raw configuration."""

    rules: list[MatchRule] = []
    for config in configs:
        if isinstance(config, RuleConfig):
            validated = config
        else:
            try:
                validated = RuleConfig.model_validate(config)
            except ValidationError as exc:  # pragma: no cover - defensive guard
                raise ValueError(str(exc)) from exc
        rules.append(_instantiate_rule(validated))
    return rules


def load_rule_configs(path: Path) -> list[Mapping[str, Any]]:
    """Load rule configuration from JSON or YAML file."""

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return []
    if isinstance(data, Mapping):
        rules = data.get("rules")
        if isinstance(rules, Sequence):
            return list(rules)
        msg = "rule configuration must contain a 'rules' sequence"
        raise ValueError(msg)
    if isinstance(data, Sequence):
        return list(data)
    msg = "unsupported rule configuration format"
    raise ValueError(msg)


def load_rules(path: Path) -> list[MatchRule]:
    """Load and build rules from configuration file."""

    return build_rules(load_rule_configs(path))


__all__ = [
    "MatchRule",
    "RuleEvaluation",
    "ExactMatchRule",
    "FuzzyMatchRule",
    "ToleranceRule",
    "RuleConfig",
    "build_rules",
    "load_rules",
    "load_rule_configs",
]

