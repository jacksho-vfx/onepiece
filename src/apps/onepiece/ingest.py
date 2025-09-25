"""Backward compatible entry point for the ingest CLI commands."""

from src.apps.onepiece.aws.ingest import app

__all__ = ["app"]
