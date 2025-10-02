from typing import Protocol
from libraries.render.base import SubmissionResult


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
    ) -> SubmissionResult: ...
