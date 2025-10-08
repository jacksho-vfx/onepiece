from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

import fastapi.security
import fastapi.security.api_key
import pytest
from fastapi.security.http import HTTPAuthorizationCredentials

import apps.trafalgar.web.security as security


PrincipalProvider = Callable[[], security.AuthenticatedPrincipal]


def patch_security(
    monkeypatch: pytest.MonkeyPatch, *, roles: Iterable[str]
) -> PrincipalProvider:
    """Patch authentication dependencies to return a principal with the given roles."""

    roles_set = set(roles)

    def provide_principal() -> security.AuthenticatedPrincipal:
        return security.AuthenticatedPrincipal(
            identifier="test-user",
            scheme="Bearer",
            roles=set(roles_set),
        )

    class DummyCredentialStore:
        def authenticate_bearer(self, token: str) -> security.AuthenticatedPrincipal:  # pragma: no cover - simple stub
            return provide_principal()

        def authenticate_api_key(
            self, key: str, secret: str | None = None
        ) -> security.AuthenticatedPrincipal:  # pragma: no cover - simple stub
            return provide_principal()

    monkeypatch.setattr(
        fastapi.security.HTTPBearer,
        "__call__",
        lambda self, request=None: HTTPAuthorizationCredentials(
            scheme="Bearer", credentials="test-bearer-token"
        ),
    )
    monkeypatch.setattr(
        fastapi.security.api_key.APIKeyHeader,
        "__call__",
        lambda self, request=None: "test-api-key",
    )
    monkeypatch.setattr(
        security,
        "get_credential_store",
        lambda *args, **kwargs: DummyCredentialStore(),
    )

    return provide_principal


__all__ = ["patch_security"]
