"""Minimal stub of the :mod:`pytest_mock` package used in tests.

This provides enough behaviour for the unit tests in this kata without
pulling in the real third-party dependency.  Only the small portion of the
API that the tests exercise is implemented.
"""

from __future__ import annotations

from typing import Any
from unittest import mock


class MockerFixture:
    """Lightweight replacement for :class:`pytest_mock.MockerFixture`.

    The real implementation integrates with pytest to automatically clean up
    patches.  For the purposes of these tests we keep track of active patches
    and expose ``stopall`` so the fixture in ``conftest`` can perform the
    necessary teardown.
    """

    def __init__(self) -> None:
        self._patches: list[mock._patch] = []
        self.Mock = mock.Mock
        self.MagicMock = mock.MagicMock
        self.AsyncMock = getattr(mock, "AsyncMock", mock.Mock)

    def patch(self, target: str, *args: Any, **kwargs: Any) -> Any:
        patcher = mock.patch(target, *args, **kwargs)
        result = patcher.start()
        self._patches.append(patcher)
        return result

    def stopall(self) -> None:
        while self._patches:
            self._patches.pop().stop()


__all__ = ["MockerFixture"]
