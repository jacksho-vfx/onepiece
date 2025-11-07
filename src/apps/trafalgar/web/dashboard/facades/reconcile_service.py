"""Reconcile data aggregation for the Trafalgar dashboard."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from apps.trafalgar.providers.providers import (
    ProviderNotFoundError,
    ReconcileDataProvider,
    initialize_providers,
)
from libraries.automation.reconcile import comparator

__all__ = ["ReconcileService"]


def _resolve_reconcile_provider(
    provider: ReconcileDataProvider | str | None,
) -> ReconcileDataProvider:
    """Return a :class:`ReconcileDataProvider` instance for *provider*."""

    if isinstance(provider, ReconcileDataProvider):
        return provider

    if provider is not None and not isinstance(provider, str):
        msg = (
            "ReconcileService provider must be a ReconcileDataProvider instance,"
            " a provider name, or None."
        )
        raise TypeError(msg)

    registry = initialize_providers()
    try:
        if isinstance(provider, str):
            resolved = registry.create("reconcile", provider)
        else:
            resolved = registry.create_default("reconcile")
    except ProviderNotFoundError as exc:
        if provider is None:
            msg = "No default reconcile provider is configured."
        else:
            msg = f"Unknown reconcile provider '{provider}'."
        raise RuntimeError(msg) from exc

    if not isinstance(resolved, ReconcileDataProvider):
        msg = (
            "Resolved reconcile provider does not implement ReconcileDataProvider: "
            f"{type(resolved).__name__}"
        )
        raise TypeError(msg)

    return resolved


class ReconcileService:
    """Summarise mismatches between ShotGrid, filesystem and S3 data."""

    def __init__(
        self,
        provider: ReconcileDataProvider | str | None = None,
        *,
        comparator_fn: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    ) -> None:
        self._provider = _resolve_reconcile_provider(provider)
        self._comparator = comparator_fn or comparator.compare_datasets

    def list_errors(self) -> list[Mapping[str, Any]]:
        payload = self._provider.load()
        shotgrid = payload.get("shotgrid", [])
        filesystem = payload.get("filesystem", [])
        s3 = payload.get("s3")
        return list(self._comparator(shotgrid, filesystem, s3=s3))

    def summarise_errors(self) -> list[dict[str, Any]]:
        mismatches = self.list_errors()
        grouped: dict[tuple[str, str], dict[str, Any]] = {}

        for mismatch in mismatches:
            mismatch_type = str(mismatch.get("type") or "unknown")
            path_value = ""
            for key in ("path", "key"):
                value = mismatch.get(key)
                if value:
                    path_value = str(value)
                    break
            group = grouped.setdefault(
                (mismatch_type, path_value),
                {"type": mismatch_type, "path": path_value, "count": 0, "shots": set()},
            )
            group["count"] += 1
            shot = mismatch.get("shot")
            if shot:
                group["shots"].add(str(shot))

        summary: list[dict[str, Any]] = []
        for _, data in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1])
        ):
            summary.append(
                {
                    "type": data["type"],
                    "path": data["path"],
                    "count": data["count"],
                    "shots": sorted(data["shots"]),
                }
            )

        return summary
