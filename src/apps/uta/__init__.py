"""Web GUI for interacting with the OnePiece toolchain."""

from .version import UTA_VERSION, __version__
from .web import app

__all__ = ["app", "UTA_VERSION", "__version__"]
