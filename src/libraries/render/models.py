from typing import Protocol
from collections.abc import Callable

from libraries.render.base import AdapterCapabilities, SubmissionResult


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
