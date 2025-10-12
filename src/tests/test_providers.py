from __future__ import annotations

from importlib.metadata import EntryPoint
from typing import Any, Mapping, Sequence

import pytest

from apps.trafalgar.providers import (
    DeliveryProvider,
    ProviderConfigurationError,
    ProviderMetadata,
    ProviderNotFoundError,
    ProviderRegistry,
    ReconcileDataProvider,
)


class ExampleDeliveryProvider(DeliveryProvider):
    metadata = ProviderMetadata(
        name="example-delivery",
        version="1.0",
        data_schema={},
        capabilities=("testing",),
    )

    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]:
        return []


class BrokenDeliveryProvider(DeliveryProvider):
    metadata = object()  # type: ignore[assignment]

    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]:  # pragma: no cover - not executed
        return []


class EntryPointDeliveryProvider(DeliveryProvider):
    metadata = ProviderMetadata(
        name="entry-delivery",
        version="1.0",
        data_schema={},
        capabilities=("entry",),
    )

    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]:
        return []


class EntryPointReconcileProvider(ReconcileDataProvider):
    metadata = ProviderMetadata(
        name="entry-reconcile",
        version="1.0",
        data_schema={},
        capabilities=("entry",),
    )

    def load(self) -> Mapping[str, Any]:
        return {}


def test_provider_registry_registers_and_creates() -> None:
    registry = ProviderRegistry()
    registry.register(ExampleDeliveryProvider, default=True)

    instance = registry.create_default("delivery")
    assert isinstance(instance, ExampleDeliveryProvider)
    available = registry.available("delivery")
    assert "example-delivery" in available
    assert available["example-delivery"].capabilities == ("testing",)


def test_provider_registry_reports_missing_provider() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderNotFoundError):
        registry.create("delivery", "missing")


def test_provider_registry_rejects_invalid_metadata() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderConfigurationError):
        registry.register(BrokenDeliveryProvider)


def test_provider_registry_loads_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry()

    entry_points = [
        EntryPoint(
            name="entry-delivery",
            value="tests.test_providers:EntryPointDeliveryProvider",
            group="onepiece.providers",
        ),
        EntryPoint(
            name="entry-reconcile",
            value="tests.test_providers:EntryPointReconcileProvider",
            group="onepiece.providers",
        ),
    ]

    registry.load_entry_points(entry_points)

    delivery = registry.create("delivery", "entry-delivery")
    reconcile = registry.create("reconcile", "entry-reconcile")

    assert isinstance(delivery, EntryPointDeliveryProvider)
    assert isinstance(reconcile, EntryPointReconcileProvider)
