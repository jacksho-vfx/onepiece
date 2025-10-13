"""Provider interfaces and registry for Trafalgar services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Any, ClassVar, Iterable, Mapping, Sequence, TypeVar


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Metadata exposed by providers for discovery."""

    name: str
    version: str
    data_schema: Mapping[str, Any] | None = None
    capabilities: Sequence[str] = ()

    def __post_init__(self) -> None:  # pragma: no cover - dataclass hook
        if not self.name:
            msg = "provider metadata must define a non-empty name"
            raise ValueError(msg)
        if not self.version:
            msg = "provider metadata must define a non-empty version"
            raise ValueError(msg)


class ProviderError(RuntimeError):
    """Base error raised when dealing with providers."""


class ProviderConfigurationError(ProviderError):
    """Raised when a provider fails validation."""


class ProviderNotFoundError(ProviderError):
    """Raised when a provider cannot be located."""


ProviderType = TypeVar("ProviderType", bound="Provider")


class Provider(ABC):
    """Base interface for pluggable providers."""

    provider_type: ClassVar[str]
    metadata: ClassVar[ProviderMetadata]

    @classmethod
    def validate_metadata(cls) -> ProviderMetadata:
        """Validate and normalise the provider metadata."""

        metadata = getattr(cls, "metadata", None)
        if not isinstance(metadata, ProviderMetadata):
            msg = f"provider {cls.__name__} must define ProviderMetadata"
            raise ProviderConfigurationError(msg)
        return metadata


class DeliveryProvider(Provider, ABC):
    """Provide delivery metadata for dashboard views."""

    provider_type: ClassVar[str] = "delivery"

    @abstractmethod
    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]:
        """Return delivery payloads for the given project."""


class ReconcileDataProvider(Provider, ABC):
    """Return reconciliation datasets used for mismatch detection."""

    provider_type: ClassVar[str] = "reconcile"

    @abstractmethod
    def load(self) -> Mapping[str, Any]:
        """Load reconciliation data from backing services."""


class ProviderRegistry:
    """Registry used to manage provider discovery."""

    def __init__(self) -> None:
        self._providers: dict[str, dict[str, type[Provider]]] = defaultdict(dict)
        self._defaults: dict[str, str] = {}

    def register(
        self,
        provider_cls: type[ProviderType],
        *,
        default: bool = False,
    ) -> None:
        """Register a provider class with the registry."""

        if not issubclass(provider_cls, Provider):
            msg = f"{provider_cls!r} is not a Provider subclass"
            raise ProviderConfigurationError(msg)

        provider_type = getattr(provider_cls, "provider_type", "")
        if not provider_type:
            msg = f"provider {provider_cls.__name__} must define provider_type"
            raise ProviderConfigurationError(msg)

        metadata = provider_cls.validate_metadata()
        providers_for_type = self._providers[provider_type]
        existing_cls = providers_for_type.get(metadata.name)
        if existing_cls is not None:
            if existing_cls is provider_cls:
                return
            msg = (
                f"provider '{metadata.name}' already registered for type "
                f"'{provider_type}'"
            )
            raise ProviderConfigurationError(msg)

        providers_for_type[metadata.name] = provider_cls
        if default or provider_type not in self._defaults:
            self._defaults[provider_type] = metadata.name

    def get(self, provider_type: str, name: str) -> type[Provider]:
        """Return a provider class by name."""

        try:
            return self._providers[provider_type][name]
        except KeyError as exc:  # pragma: no cover - simple guard
            msg = f"provider '{name}' not found for type '{provider_type}'"
            raise ProviderNotFoundError(msg) from exc

    def create(self, provider_type: str, name: str, **kwargs: Any) -> Provider:
        """Create a provider instance."""

        provider_cls = self.get(provider_type, name)
        return provider_cls(**kwargs)

    def get_default_name(self, provider_type: str) -> str:
        try:
            return self._defaults[provider_type]
        except KeyError as exc:  # pragma: no cover - simple guard
            msg = f"no default provider registered for '{provider_type}'"
            raise ProviderNotFoundError(msg) from exc

    def create_default(self, provider_type: str, **kwargs: Any) -> Provider:
        name = self.get_default_name(provider_type)
        return self.create(provider_type, name, **kwargs)

    def available(self, provider_type: str) -> Mapping[str, ProviderMetadata]:
        providers = self._providers.get(provider_type, {})
        return {name: provider_cls.metadata for name, provider_cls in providers.items()}

    def load_entry_points(self, discovered: Iterable[EntryPoint] | None = None) -> None:
        """Discover providers exposed through entry points."""

        if discovered is None:
            discovered_iterable = entry_points()
            if hasattr(discovered_iterable, "select"):
                discovered = discovered_iterable.select(group="onepiece.providers")
            else:  # pragma: no cover - Python <3.10 support
                discovered = discovered_iterable.get("onepiece.providers", [])  # type: ignore[attr-defined]

        for entry_point in discovered or []:
            provider_cls = entry_point.load()
            self.register(provider_cls)


class DefaultReconcileProvider(ReconcileDataProvider):
    metadata: ClassVar[ProviderMetadata] = ProviderMetadata(
        name="default-reconcile",
        version="1.0",
        data_schema={
            "shotgrid": "Sequence[Mapping[str, Any]]",
            "filesystem": "Sequence[Mapping[str, Any]]",
            "s3": "Optional[Mapping[str, Any]]",
        },
        capabilities=("default",),
    )

    def load(self) -> Mapping[str, Any]:
        return {"shotgrid": [], "filesystem": [], "s3": None}


class DummyDeliveryProvider(DeliveryProvider):
    metadata: ClassVar[ProviderMetadata] = ProviderMetadata(
        name="dummy-delivery",
        version="1.0",
        data_schema={
            "type": "sequence",
            "items": {
                "type": "object",
                "required": ["project", "manifest"],
            },
        },
        capabilities=("in-memory",),
    )

    def __init__(self, deliveries: Sequence[Mapping[str, Any]] | None = None) -> None:
        self._deliveries = [dict(item) for item in deliveries or ()]

    def list_deliveries(self, project_name: str) -> Sequence[Mapping[str, Any]]:
        return [
            delivery
            for delivery in self._deliveries
            if delivery.get("project") == project_name
        ]


class S3DeliveryProvider(DeliveryProvider):
    metadata: ClassVar[ProviderMetadata] = ProviderMetadata(
        name="s3-delivery",
        version="1.0",
        data_schema={
            "type": "sequence",
            "items": {
                "type": "object",
                "required": ["bucket", "key"],
            },
        },
        capabilities=("s3", "read"),
    )

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client

    def list_deliveries(
        self, project_name: str
    ) -> Sequence[Mapping[str, Any]]:  # pragma: no cover - stub
        return []


def initialize_providers() -> ProviderRegistry:
    """Initialize provider registry by loading all entry points."""
    registry = ProviderRegistry()
    registry.register(DefaultReconcileProvider, default=True)
    registry.register(DummyDeliveryProvider, default=True)
    registry.register(S3DeliveryProvider)
    registry.load_entry_points()
    return registry
