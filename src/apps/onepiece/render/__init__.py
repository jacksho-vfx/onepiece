"""Render farm CLI commands."""

from pathlib import Path
from typing import Any

import structlog

from .submit import app

log = structlog.get_logger(__name__)


def publish(
    *, job_id: str, publish_root: str, profile: str | None = None, **kwargs: Any
) -> dict[str, Any]:
    """Record render job publication metadata for downstream consumers."""

    destination = Path(publish_root)
    destination.mkdir(parents=True, exist_ok=True)

    log.info(
        "render.publish", job_id=job_id, publish_root=str(destination), profile=profile
    )

    payload = {"job_id": job_id, "publish_root": str(destination)}
    if profile is not None:
        payload["profile"] = profile
    if kwargs:
        payload["metadata"] = dict(kwargs)  # type: ignore[assignment]
    return payload


__all__ = ["app", "publish"]
