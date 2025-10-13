"""Public exports for the Trafalgar provider package."""

from __future__ import annotations

# Re-export the default reconcile provider so that it is discoverable via
# Python entry points. Importlib expects the target object to live on the
# module referenced in the entry point definition, therefore the object must be
# defined here rather than only within ``providers.py``. Previously the module
# did not expose :class:`DefaultReconcileProvider`, causing entry point loading
# to fail during tests.

from .providers import DefaultReconcileProvider

__all__ = ["DefaultReconcileProvider"]
