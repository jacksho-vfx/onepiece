"""Backward compatible entry point for the ingest CLI commands."""

from apps.onepiece.aws.ingest import app

__all__ = ["app"]
