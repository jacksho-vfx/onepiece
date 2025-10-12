"""Reconciliation job orchestrating multi-provider comparisons."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping, MutableSequence, Sequence

from pydantic import BaseModel, Field

from libraries.reconcile.rules import MatchRule, RuleEvaluation


class ReconciliationRecord(BaseModel):
    """Normalised record exchanged between the job and providers."""

    provider: str
    data: Mapping[str, Any]

    def key(self, field: str) -> Any:
        return self.data.get(field)


class FieldDifference(BaseModel):
    field: str
    delivery_value: Any
    source_value: Any


class ProviderMatchResult(BaseModel):
    provider: str
    matched: bool
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    record: ReconciliationRecord | None = None
    differences: Sequence[FieldDifference] = ()
    rule_trace: Sequence[RuleEvaluation] = ()


class ReconciliationMatch(BaseModel):
    delivery: ReconciliationRecord
    sources: Sequence[ProviderMatchResult]

    @property
    def fully_matched(self) -> bool:
        return all(match.matched for match in self.sources)


class ProviderMetrics(BaseModel):
    provider: str
    total_records: int
    matched_records: int
    unmatched_records: int
    matched_percentage: float


class ReconciliationSummary(BaseModel):
    total_deliveries: int
    matched_deliveries: int
    unmatched_deliveries: int
    matched_percentage: float
    runtime_seconds: float
    provider_metrics: Sequence[ProviderMetrics]


class ReconciliationResult(BaseModel):
    summary: ReconciliationSummary
    matches: Sequence[ReconciliationMatch]
    unmatched_delivery_keys: Sequence[Any]
    unmatched_sources: Mapping[str, Sequence[ReconciliationRecord]]


@dataclass(slots=True)
class _ProviderState:
    provider: str
    records: MutableSequence[ReconciliationRecord]
    matched: int = 0

    @property
    def total(self) -> int:
        return len(self.records) + self.matched


class ReconciliationJob:
    """Coordinate reconciliation between delivery and source providers."""

    def __init__(
        self,
        *,
        delivery_provider: Any,
        source_providers: Sequence[Any],
        rules: Sequence[MatchRule],
        key_field: str,
        minimum_score: float = 0.6,
    ) -> None:
        if not rules:
            msg = "reconciliation requires at least one rule"
            raise ValueError(msg)
        if not (0.0 <= minimum_score <= 1.0):
            msg = "minimum_score must be between 0.0 and 1.0"
            raise ValueError(msg)

        self.delivery_provider = delivery_provider
        self.source_providers = list(source_providers)
        self.rules = list(rules)
        self.key_field = key_field
        self.minimum_score = minimum_score

    @staticmethod
    def _provider_name(provider: Any) -> Any:
        return getattr(provider, "name", provider.__class__.__name__)

    def _load_delivery(self) -> list[ReconciliationRecord]:
        if hasattr(self.delivery_provider, "load"):
            raw = self.delivery_provider.load()
        elif hasattr(self.delivery_provider, "list_deliveries"):
            raw = self.delivery_provider.list_deliveries()
        else:  # pragma: no cover - defensive guard
            msg = "delivery provider must implement load() or list_deliveries()"
            raise AttributeError(msg)

        provider_name = self._provider_name(self.delivery_provider)
        return [
            ReconciliationRecord(provider=provider_name, data=dict(record))
            for record in raw or []
        ]

    def _load_sources(self) -> dict[str, _ProviderState]:
        states: dict[str, _ProviderState] = {}
        for provider in self.source_providers:
            if hasattr(provider, "load"):
                raw = provider.load()
            else:  # pragma: no cover - defensive guard
                msg = f"source provider {provider!r} must implement load()"
                raise AttributeError(msg)

            name = self._provider_name(provider)
            records = [
                ReconciliationRecord(provider=name, data=dict(record))
                for record in raw or []
            ]
            states[name] = _ProviderState(provider=name, records=records)
        return states

    def _evaluate_candidate(
        self,
        delivery: ReconciliationRecord,
        candidate: ReconciliationRecord,
        *,
        provider: str,
    ) -> tuple[float, list[RuleEvaluation]]:
        evaluations: list[RuleEvaluation] = []
        total_weight = 0.0
        weighted_score = 0.0
        for rule in self.rules:
            if not rule.applicable(provider):
                continue
            evaluation = rule.evaluate(delivery.data, candidate.data, provider=provider)
            evaluations.append(evaluation)
            total_weight += evaluation.weight
            weighted_score += evaluation.score * evaluation.weight

        if total_weight == 0.0:
            return 0.0, evaluations

        score = weighted_score / total_weight
        return score, evaluations

    @staticmethod
    def _build_differences(
        delivery: ReconciliationRecord,
        candidate: ReconciliationRecord,
    ) -> list[FieldDifference]:
        differences: list[FieldDifference] = []
        keys = set(delivery.data) | set(candidate.data)
        for field in sorted(keys):
            lhs = delivery.data.get(field)
            rhs = candidate.data.get(field)
            if lhs != rhs:
                differences.append(
                    FieldDifference(
                        field=field,
                        delivery_value=lhs,
                        source_value=rhs,
                    )
                )
        return differences

    def _match_against_provider(
        self,
        delivery: ReconciliationRecord,
        state: _ProviderState,
    ) -> ProviderMatchResult:
        provider = state.provider
        best_candidate: tuple[int, ReconciliationRecord] | None = None
        best_score = -1.0
        best_trace: list[RuleEvaluation] = []

        for index, candidate in enumerate(state.records):
            score, evaluations = self._evaluate_candidate(
                delivery, candidate, provider=provider
            )
            if score > best_score:
                best_candidate = (index, candidate)
                best_score = score
                best_trace = evaluations

        matched = best_candidate is not None and best_score >= self.minimum_score
        if not matched:
            return ProviderMatchResult(
                provider=provider,
                matched=False,
                score=best_score if best_score >= 0 else None,
                record=None,
                differences=(),
                rule_trace=best_trace,
            )

        index, candidate = best_candidate  # type: ignore[misc]

        state.records.pop(index)
        state.matched += 1

        return ProviderMatchResult(
            provider=provider,
            matched=True,
            score=best_score,
            record=candidate,
            differences=self._build_differences(delivery, candidate),
            rule_trace=best_trace,
        )

    def run(self) -> ReconciliationResult:
        """Execute the reconciliation workflow."""

        start_time = perf_counter()
        deliveries = self._load_delivery()
        source_states = self._load_sources()

        matches: list[ReconciliationMatch] = []
        unmatched_delivery_keys: list[Any] = []

        for delivery in deliveries:
            provider_results: list[ProviderMatchResult] = []
            for state in source_states.values():
                provider_results.append(self._match_against_provider(delivery, state))

            match = ReconciliationMatch(delivery=delivery, sources=provider_results)
            matches.append(match)
            if not match.fully_matched:
                unmatched_delivery_keys.append(delivery.key(self.key_field))

        runtime = perf_counter() - start_time

        matched_deliveries = sum(1 for match in matches if match.fully_matched)
        total_deliveries = len(matches)
        unmatched_deliveries = total_deliveries - matched_deliveries
        matched_percentage = (
            (matched_deliveries / total_deliveries) * 100 if total_deliveries else 100.0
        )

        provider_metrics: list[ProviderMetrics] = []
        unmatched_sources: dict[str, list[ReconciliationRecord]] = defaultdict(list)
        for state in source_states.values():
            provider_metrics.append(
                ProviderMetrics(
                    provider=state.provider,
                    total_records=state.total,
                    matched_records=state.matched,
                    unmatched_records=len(state.records),
                    matched_percentage=(
                        (state.matched / state.total) * 100 if state.total else 100.0
                    ),
                )
            )
            unmatched_sources[state.provider].extend(state.records)

        summary = ReconciliationSummary(
            total_deliveries=total_deliveries,
            matched_deliveries=matched_deliveries,
            unmatched_deliveries=unmatched_deliveries,
            matched_percentage=matched_percentage,
            runtime_seconds=runtime,
            provider_metrics=provider_metrics,
        )

        return ReconciliationResult(
            summary=summary,
            matches=matches,
            unmatched_delivery_keys=unmatched_delivery_keys,
            unmatched_sources=unmatched_sources,
        )


__all__ = [
    "ReconciliationJob",
    "ReconciliationRecord",
    "ReconciliationResult",
    "ReconciliationSummary",
    "ReconciliationMatch",
    "ProviderMatchResult",
    "ProviderMetrics",
    "FieldDifference",
]
