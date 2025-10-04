"""Re-export dashboard application for uvicorn compatibility."""

from apps.trafalgar.web.dashboard import app

__all__ = ["app"]
