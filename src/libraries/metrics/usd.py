"""Shared helpers for emitting USD-centric timing metrics from DCC scripts.

The :class:`USDMetricClient` is intentionally lightweight so it can be imported
from application scripting environments (Cinema 4D, Unreal, or Nuke) without
dragging in additional dependencies.  When a metrics endpoint is not
configured the client will silently noop so DCC workflows keep running even if
the central collector is unavailable.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Mapping

import requests  # type: ignore[import-untyped]
import structlog

log = structlog.get_logger(__name__)


_default_endpoint = os.getenv("USD_METRICS_ENDPOINT")


@dataclass(frozen=True)
class USDMetricEvent:
    """Payload describing a timed DCC operation."""

    dcc: str
    stage: str
    duration_ms: float
    sequence: str | None = None
    asset: str | None = None
    occurred_at: datetime = datetime.now(timezone.utc)
    metadata: Mapping[str, Any] | None = None


class USDMetricClient:
    """Send USD timing events to a central collector."""

    def __init__(
        self, *, endpoint: str | None = None, session: requests.Session | None = None
    ) -> None:
        self._endpoint = endpoint or _default_endpoint
        self._session = session or requests.Session()

    def record(self, event: USDMetricEvent) -> None:
        """Push a timing event to the configured endpoint.

        When no endpoint is configured or a delivery error occurs the payload is
        logged and execution continues.  This keeps DCC scripting integrations
        resilient to network availability without losing observability when the
        collector is present.
        """

        if not self._endpoint:
            log.debug(
                "usd_metrics.skip", reason="no endpoint configured", stage=event.stage
            )
            return

        payload = {
            "dcc": event.dcc,
            "stage": event.stage,
            "sequence": event.sequence,
            "asset": event.asset,
            "duration_ms": event.duration_ms,
            "occurred_at": event.occurred_at.isoformat(),
            "metadata": dict(event.metadata or {}),
        }

        try:
            response = self._session.post(
                f"{self._endpoint.rstrip('/')}/events",
                json={"events": [payload]},
                timeout=2,
            )
            response.raise_for_status()
        except Exception as exc:  # pragma: no cover - defensive guard for DCC runtimes
            log.warning(
                "usd_metrics.delivery_failed",
                endpoint=self._endpoint,
                stage=event.stage,
                error=str(exc),
            )

    @contextmanager
    def time_block(
        self,
        *,
        dcc: str,
        stage: str,
        sequence: str | None = None,
        asset: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Any:
        """Context manager that emits a timing event after the wrapped block."""

        start = perf_counter()
        status = "ok"
        try:
            yield
        except Exception:
            status = "error"
            raise
        finally:
            duration_ms = (perf_counter() - start) * 1000
            merged_metadata = dict(metadata or {})
            merged_metadata.setdefault("status", status)
            self.record(
                USDMetricEvent(
                    dcc=dcc,
                    stage=stage,
                    duration_ms=duration_ms,
                    sequence=sequence,
                    asset=asset,
                    metadata=merged_metadata,
                )
            )


__all__ = ["USDMetricClient", "USDMetricEvent"]
