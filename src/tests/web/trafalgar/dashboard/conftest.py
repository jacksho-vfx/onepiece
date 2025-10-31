from __future__ import annotations

import copy
from typing import Any, Callable, Generator, Iterable, Mapping, Sequence, Type

import pytest

from apps.trafalgar.providers.providers import (
    DeliveryProvider,
    ProviderMetadata,
    ReconcileDataProvider,
    initialize_providers,
)
from apps.trafalgar.web import dashboard


initialize_providers()


class _DummyShotgridClient:
    def __init__(self, versions: Sequence[dict[str, Any]]) -> None:
        self._versions = list(versions)
        self.calls = 0

    def list_versions(self) -> Sequence[dict[str, Any]]:
        self.calls += 1
        return self._versions


class _DummyReconcileProvider(ReconcileDataProvider):  # type: ignore[misc]
    metadata = ProviderMetadata(
        name="test-reconcile",
        version="1.0",
        data_schema={},
        capabilities=("testing",),
    )

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def load(self) -> dict[str, Any]:
        return self._payload


class _DummyDeliveryProvider(DeliveryProvider):  # type: ignore[misc]
    metadata = ProviderMetadata(
        name="test-delivery",
        version="1.0",
        data_schema={},
        capabilities=("testing",),
    )

    def __init__(self, deliveries: Sequence[dict[str, Any]]) -> None:
        self._deliveries = list(deliveries)

    def list_deliveries(self, project_name: str) -> Sequence[dict[str, Any]]:
        return [
            delivery
            for delivery in self._deliveries
            if delivery.get("project") == project_name
        ]


class _SequencedDeliveryProvider(DeliveryProvider):  # type: ignore[misc]
    metadata = ProviderMetadata(
        name="sequenced-delivery",
        version="1.0",
        data_schema={},
        capabilities=("testing",),
    )

    def __init__(self, responses: Sequence[Sequence[Mapping[str, Any]]]) -> None:
        self._responses = [list(response) for response in responses]
        self.requests: list[str] = []

    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]:
        self.requests.append(project_name)
        if self._responses:
            response = self._responses.pop(0)
        else:
            response = []
        return [copy.deepcopy(item) for item in response]


class _DummyIngestFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self._summary = summary
        self.calls: list[int] = []

    def summarise_recent_runs(self, limit: int = 10) -> Mapping[str, Any]:
        self.calls.append(limit)
        return self._summary


class _FakeMonotonic:
    def __init__(self) -> None:
        self._value = 0.0

    def advance(self, seconds: float) -> None:
        self._value += seconds

    def __call__(self) -> float:
        return self._value


class _DummyRenderFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self._summary = summary
        self.calls: int = 0

    async def summarise_jobs(self) -> Mapping[str, Any]:
        self.calls += 1
        return self._summary


class _DummyReviewFacade:
    def __init__(self, summary: Mapping[str, Any]) -> None:
        self._summary = summary
        self.project_calls: list[list[str]] = []

    def summarise_projects(self, project_names: Iterable[str]) -> Mapping[str, Any]:
        self.project_calls.append(list(project_names))
        return self._summary


@pytest.fixture(autouse=True)
def _clear_overrides() -> Generator[None, None, None]:
    dashboard.app.dependency_overrides.clear()
    dashboard.get_shotgrid_service.cache_clear()
    for attr in (
        "dashboard_cache_ttl",
        "dashboard_cache_max_records",
        "dashboard_cache_max_projects",
    ):
        if hasattr(dashboard.app.state, attr):
            delattr(dashboard.app.state, attr)
    yield
    dashboard.app.dependency_overrides.clear()
    dashboard.get_shotgrid_service.cache_clear()
    for attr in (
        "dashboard_cache_ttl",
        "dashboard_cache_max_records",
        "dashboard_cache_max_projects",
    ):
        if hasattr(dashboard.app.state, attr):
            delattr(dashboard.app.state, attr)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def dummy_shotgrid_client_cls() -> Type[_DummyShotgridClient]:
    return _DummyShotgridClient


@pytest.fixture
def dummy_reconcile_provider_cls() -> Type[_DummyReconcileProvider]:
    return _DummyReconcileProvider


@pytest.fixture
def dummy_delivery_provider_cls() -> Type[_DummyDeliveryProvider]:
    return _DummyDeliveryProvider


@pytest.fixture
def delivery_provider_factory() -> Callable[..., _SequencedDeliveryProvider]:
    def factory(*responses: Sequence[Mapping[str, Any]]) -> _SequencedDeliveryProvider:
        return _SequencedDeliveryProvider(responses)

    return factory


@pytest.fixture
def dummy_ingest_facade_cls() -> Type[_DummyIngestFacade]:
    return _DummyIngestFacade


@pytest.fixture
def dummy_render_facade_cls() -> Type[_DummyRenderFacade]:
    return _DummyRenderFacade


@pytest.fixture
def dummy_review_facade_cls() -> Type[_DummyReviewFacade]:
    return _DummyReviewFacade


@pytest.fixture
def fake_monotonic_cls() -> Type[_FakeMonotonic]:
    return _FakeMonotonic
