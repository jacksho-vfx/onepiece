from collections.abc import Callable
from typing import Protocol

from libraries.automation.render.base import AdapterCapabilities, SubmissionResult


class RenderAdapter(Protocol):
    def __call__(
        self,
        *,
        scene: str,
        frames: str,
        output: str,
        dcc: str,
        priority: int,
        user: str,
        chunk_size: int | None,
    ) -> SubmissionResult: ...


CapabilityProvider = Callable[[], AdapterCapabilities]


__all__ = ["RenderAdapter", "CapabilityProvider"]
