"""Delivery manifest aggregation helpers for the Trafalgar dashboard."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Hashable, Mapping, Sequence

from apps.trafalgar.providers.providers import (
    DeliveryProvider,
    ProviderNotFoundError,
    initialize_providers,
)
from libraries.automation.delivery.manifest import get_manifest_data

from ..auth import _parse_datetime

__all__ = ["DeliveryService"]


def _resolve_delivery_provider(
    provider: DeliveryProvider | str | None,
) -> DeliveryProvider:
    """Return a :class:`DeliveryProvider` instance for *provider*."""

    if isinstance(provider, DeliveryProvider):
        return provider

    if provider is not None and not isinstance(provider, str):
        msg = (
            "DeliveryService provider must be a DeliveryProvider instance,"
            " a provider name, or None."
        )
        raise TypeError(msg)

    registry = initialize_providers()
    try:
        if isinstance(provider, str):
            resolved = registry.create("delivery", provider)
        else:
            resolved = registry.create_default("delivery")
    except ProviderNotFoundError as exc:
        if provider is None:
            msg = "No default delivery provider is configured."
        else:
            msg = f"Unknown delivery provider '{provider}'."
        raise RuntimeError(msg) from exc

    if not isinstance(resolved, DeliveryProvider):
        msg = (
            "Resolved delivery provider does not implement DeliveryProvider: "
            f"{type(resolved).__name__}"
        )
        raise TypeError(msg)

    return resolved


class DeliveryService:
    """Summarise delivery manifests for dashboard consumption."""

    def __init__(
        self,
        provider: DeliveryProvider | str | None = None,
        *,
        manifest_cache_size: int = 32,
    ) -> None:
        self._provider = _resolve_delivery_provider(provider)
        self._manifest_cache: OrderedDict[Hashable, dict[str, Any]] = OrderedDict()
        self._manifest_cache_size = max(0, manifest_cache_size)

    def _manifest_cache_key(self, delivery: Mapping[str, Any]) -> Hashable | None:
        for key in ("id", "delivery_id"):
            value = delivery.get(key)
            if isinstance(value, Hashable):
                return value
        return None

    def _delivery_cache_keys(self, delivery: Mapping[str, Any]) -> list[Hashable]:
        keys: list[Hashable] = []
        cache_key = self._manifest_cache_key(delivery)
        if cache_key is not None:
            keys.append(cache_key)
        manifest_path = delivery.get("manifest")
        if isinstance(manifest_path, str) and manifest_path:
            keys.append(manifest_path)
        return keys

    @staticmethod
    def _clone_manifest_data(manifest: Mapping[str, Any]) -> dict[str, Any]:
        files = manifest.get("files", [])
        if isinstance(files, Sequence) and not isinstance(
            files, (str, bytes, bytearray)
        ):
            cloned_files = [
                dict(item) if isinstance(item, Mapping) else item for item in files
            ]
        else:
            cloned_files = []
        return {"files": cloned_files}

    def _store_manifest(self, key: Hashable, manifest: Mapping[str, Any]) -> None:
        if self._manifest_cache_size == 0:
            return
        self._manifest_cache[key] = self._clone_manifest_data(manifest)
        self._manifest_cache.move_to_end(key)
        while len(self._manifest_cache) > self._manifest_cache_size:
            self._manifest_cache.popitem(last=False)

    def _lookup_manifest(self, key: Hashable) -> dict[str, Any] | None:
        if self._manifest_cache_size == 0:
            return None
        cached = self._manifest_cache.get(key)
        if cached is None:
            return None
        self._manifest_cache.move_to_end(key)
        return self._clone_manifest_data(cached)

    @staticmethod
    def _normalise_manifest_payload(payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, Mapping):
            return DeliveryService._clone_manifest_data(payload)
        if isinstance(payload, Sequence) and not isinstance(
            payload, (str, bytes, bytearray)
        ):
            files = [
                dict(item) if isinstance(item, Mapping) else item for item in payload
            ]
            return {"files": files}
        return None

    def list_deliveries(self, project_name: str) -> list[dict[str, Any]]:
        deliveries = self._provider.list_deliveries(project_name)
        result: list[dict[str, Any]] = []
        for delivery in deliveries:
            entries = delivery.get("entries") or []
            manifest_data = self._normalise_manifest_payload(
                delivery.get("manifest_data")
            )
            if manifest_data is None:
                manifest_data = self._normalise_manifest_payload(delivery.get("items"))

            cache_keys = self._delivery_cache_keys(delivery)
            cached_from: Hashable | None = None
            if manifest_data is None:
                for key in cache_keys:
                    cached_manifest = self._lookup_manifest(key)
                    if cached_manifest is not None:
                        manifest_data = cached_manifest
                        cached_from = key
                        break

            if manifest_data is None:
                if entries:
                    manifest_data = get_manifest_data(entries)
                else:
                    manifest_data = {"files": []}

            for key in cache_keys:
                if cached_from is not None and key == cached_from:
                    continue
                self._store_manifest(key, manifest_data)

            files = manifest_data.get("files", [])
            cache_key = self._manifest_cache_key(delivery)
            result.append(
                {
                    "project": project_name,
                    "name": delivery.get("name"),
                    "archive": delivery.get("archive"),
                    "manifest": delivery.get("manifest"),
                    "delivery_id": str(cache_key) if cache_key is not None else None,
                    "created_at": _parse_datetime(
                        delivery.get("created_at") or delivery.get("timestamp")
                    ),
                    "items": files,
                    "file_count": len(files),
                }
            )

        return result

    def get_delivery_manifest(
        self, project_name: str, identifier: str
    ) -> dict[str, Any]:
        lookup = identifier.strip()
        if not lookup:
            raise KeyError("Empty delivery identifier")

        deliveries = self._provider.list_deliveries(project_name)
        for delivery in deliveries:
            cache_keys = self._delivery_cache_keys(delivery)
            if not any(str(key) == lookup for key in cache_keys):
                continue

            for key in cache_keys:
                cached_manifest = self._lookup_manifest(key)
                if cached_manifest is not None:
                    return cached_manifest

            entries = delivery.get("entries") or []
            manifest_data = self._normalise_manifest_payload(
                delivery.get("manifest_data")
            )
            if manifest_data is None:
                manifest_data = self._normalise_manifest_payload(delivery.get("items"))
            if manifest_data is None:
                if entries:
                    manifest_data = get_manifest_data(entries)
                else:
                    manifest_data = {"files": []}

            for key in cache_keys:
                self._store_manifest(key, manifest_data)
            return manifest_data

        raise KeyError(f"Delivery not found: {identifier}")
