"""Authentication and authorisation helpers for Trafalgar web services."""

from __future__ import annotations

import hmac
import json
import os
from functools import lru_cache
from typing import Any, Callable, Iterable, Mapping, Sequence

import copy
import structlog
from fastapi import APIRouter, Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AliasChoices, BaseModel, Field, ValidationError, field_validator

logger = structlog.get_logger(__name__)


# Environment variable configuration -------------------------------------------------

CREDENTIALS_ENV = "TRAFALGAR_SERVICE_CREDENTIALS"
CREDENTIALS_FILE_ENV = "TRAFALGAR_SERVICE_CREDENTIAL_FILE"
API_KEY_HEADER_ENV = "TRAFALGAR_API_KEY_HEADER"
API_SECRET_HEADER_ENV = "TRAFALGAR_API_SECRET_HEADER"

DEFAULT_API_KEY_HEADER = "X-API-Key"
DEFAULT_API_SECRET_HEADER = "X-API-Secret"


# Role constants --------------------------------------------------------------------

ROLE_RENDER_READ = "render:read"
ROLE_RENDER_SUBMIT = "render:submit"
ROLE_RENDER_MANAGE = "render:manage"
ROLE_INGEST_READ = "ingest:read"
ROLE_REVIEW_READ = "review:read"


# Built-in credentials ----------------------------------------------------------------

_DEFAULT_CREDENTIAL_PAYLOADS: tuple[Mapping[str, Any], ...] = (
    {
        "id": "suite",
        "key": "suite-key",
        "secret": "suite-secret",
        "roles": {
            ROLE_RENDER_READ,
            ROLE_RENDER_SUBMIT,
            ROLE_RENDER_MANAGE,
            ROLE_INGEST_READ,
            ROLE_REVIEW_READ,
        },
    },
    {
        "id": "ingest-read",
        "key": "ingest-read-key",
        "secret": "ingest-read-secret",
        "roles": {ROLE_INGEST_READ},
    },
    {
        "id": "review",
        "token": "review-token",
        "roles": {ROLE_REVIEW_READ},
    },
)


class SecuritySettings(BaseModel):
    """Runtime configuration controlling authentication behaviour."""

    api_key_header: str = Field(default=DEFAULT_API_KEY_HEADER)
    api_secret_header: str = Field(default=DEFAULT_API_SECRET_HEADER)

    @field_validator("api_key_header", mode="before")
    @classmethod
    def _normalise_key_header(cls, value: str | None) -> str:
        text = (value or "").strip()
        return text or DEFAULT_API_KEY_HEADER

    @field_validator("api_secret_header", mode="before")
    @classmethod
    def _normalise_secret_header(cls, value: str | None) -> str:
        text = (value or "").strip()
        return text or DEFAULT_API_SECRET_HEADER


@lru_cache(maxsize=1)
def get_security_settings() -> SecuritySettings:
    """Return cached authentication settings derived from the environment."""

    return SecuritySettings(
        api_key_header=os.getenv(API_KEY_HEADER_ENV, DEFAULT_API_KEY_HEADER),
        api_secret_header=os.getenv(API_SECRET_HEADER_ENV, DEFAULT_API_SECRET_HEADER),
    )


def _build_api_key_header() -> APIKeyHeader:
    settings = get_security_settings()
    return APIKeyHeader(name=settings.api_key_header, auto_error=False)


def _build_api_secret_header() -> APIKeyHeader:
    settings = get_security_settings()
    return APIKeyHeader(name=settings.api_secret_header, auto_error=False)


_api_key_scheme = _build_api_key_header()
_api_secret_scheme = _build_api_secret_header()
_bearer_scheme = HTTPBearer(auto_error=False)


class CredentialRecord(BaseModel):
    """Credential definition loaded from configuration sources."""

    identifier: str = Field(validation_alias=AliasChoices("identifier", "id", "name"))
    api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("api_key", "key")
    )
    api_secret: str | None = Field(
        default=None, validation_alias=AliasChoices("api_secret", "secret")
    )
    bearer_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("bearer_token", "token", "oauth_token"),
    )
    roles: set[str] = Field(
        default_factory=set, validation_alias=AliasChoices("roles", "scopes")
    )
    description: str | None = None

    @field_validator("identifier", mode="before")
    @classmethod
    def _normalise_identifier(cls, value: Any) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("Credential identifier cannot be empty.")
        return text

    @field_validator("roles", mode="before")
    @classmethod
    def _normalise_roles(cls, value: Any) -> Iterable[str]:
        if value is None:
            return set()
        if isinstance(value, (set, frozenset)):
            return value
        if isinstance(value, str):
            return {item.strip() for item in value.split(" ") if item.strip()}
        roles: set[str] = set()
        if not isinstance(value, Iterable):
            value = [value]
        for item in value:
            if not item:
                continue
            roles.add(str(item).strip())
        return roles

    @field_validator("roles", mode="after")
    @classmethod
    def _drop_empty_roles(cls, value: set[str]) -> set[str]:
        return {role for role in value if role}

    def matches_api_key(self, key: str, secret: str | None) -> bool:
        if self.api_key is None:
            return False
        if not hmac.compare_digest(self.api_key, key):
            return False
        if self.api_secret is None:
            return secret in (None, "")
        if secret is None:
            return False
        return hmac.compare_digest(self.api_secret, secret)

    def matches_bearer(self, token: str) -> bool:
        if self.bearer_token is None:
            return False
        return hmac.compare_digest(self.bearer_token, token)

    def to_principal(self, *, scheme: str) -> "AuthenticatedPrincipal":
        return AuthenticatedPrincipal(
            identifier=self.identifier, roles=set(self.roles), scheme=scheme
        )


class CredentialStore:
    """In-memory cache of configured API credentials."""

    def __init__(self, records: Iterable[CredentialRecord]) -> None:
        self._records: list[CredentialRecord] = []
        self._api_key_index: dict[str, CredentialRecord] = {}
        self._bearer_index: dict[str, CredentialRecord] = {}

        for record in records:
            self._records.append(record)
            if record.api_key:
                self._api_key_index[record.api_key] = record
            if record.bearer_token:
                self._bearer_index[record.bearer_token] = record

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return bool(self._records)

    def authenticate_api_key(
        self, key: str, secret: str | None
    ) -> "AuthenticatedPrincipal" | None:
        record = self._api_key_index.get(key)
        if record and record.matches_api_key(key, secret):
            return record.to_principal(scheme="api-key")
        return None

    def authenticate_bearer(self, token: str) -> "AuthenticatedPrincipal" | None:
        record = self._bearer_index.get(token)
        if record and record.matches_bearer(token):
            return record.to_principal(scheme="oauth2")
        return None


def _normalise_credential_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        entries: list[Mapping[str, Any]] = []
        for key, value in payload.items():
            if isinstance(value, Mapping):
                data = dict(value)
                data.setdefault("id", key)
                entries.append(data)
        return entries
    if isinstance(payload, Sequence):
        return [item for item in payload if isinstance(item, Mapping)]
    return []


def _load_credential_sources() -> list[Mapping[str, Any]]:
    entries: list[Mapping[str, Any]] = []
    inline = os.getenv(CREDENTIALS_ENV)
    if inline:
        try:
            parsed = json.loads(inline)
        except json.JSONDecodeError as exc:
            logger.error(
                "security.credentials.invalid_json", source="env", error=str(exc)
            )
        else:
            entries.extend(_normalise_credential_payload(parsed))

    path = os.getenv(CREDENTIALS_FILE_ENV)
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                parsed = json.load(handle)
        except OSError as exc:
            logger.error(
                "security.credentials.file_unreadable", path=path, error=str(exc)
            )
        except json.JSONDecodeError as exc:
            logger.error("security.credentials.file_invalid", path=path, error=str(exc))
        else:
            entries.extend(_normalise_credential_payload(parsed))

    if not entries:
        entries.extend(copy.deepcopy(_DEFAULT_CREDENTIAL_PAYLOADS))

    return entries


def _load_credential_records() -> list[CredentialRecord]:
    records: list[CredentialRecord] = []
    for entry in _load_credential_sources():
        try:
            record = CredentialRecord.model_validate(entry)
        except ValidationError as exc:
            logger.warning(
                "security.credentials.entry_invalid", entry=entry, error=str(exc)
            )
            continue
        records.append(record)
    return records


@lru_cache(maxsize=1)
def get_credential_store() -> CredentialStore:
    """Return the cached credential store used for request authentication."""

    return CredentialStore(_load_credential_records())


class AuthenticatedPrincipal(BaseModel):
    """Represents an authenticated caller and their granted roles."""

    identifier: str
    roles: set[str] = Field(default_factory=set)
    scheme: str

    def require_roles(self, required: Iterable[str], *, any_of: bool = False) -> None:
        required_set = {role for role in required if role}
        if not required_set:
            return
        granted = self.roles or set()
        if any_of:
            if granted.isdisjoint(required_set):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Caller is missing a required role.",
                )
            return
        missing = required_set - granted
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caller is missing required roles.",
            )


def authenticate_request(
    api_key: str | None = Security(_api_key_scheme),
    api_secret: str | None = Security(_api_secret_scheme),
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> AuthenticatedPrincipal:
    """Authenticate the incoming request using configured credentials."""

    store = get_credential_store()
    if not store:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service authentication has not been configured.",
        )

    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        if token:
            principal = store.authenticate_bearer(token)
            if principal:
                return principal
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token."
        )

    if api_key:
        principal = store.authenticate_api_key(api_key, api_secret)
        if principal:
            return principal
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API credentials."
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials were not provided.",
    )


def require_roles(
    *roles: str, any_of: bool = False
) -> Callable[[AuthenticatedPrincipal], AuthenticatedPrincipal]:
    """Return a dependency enforcing that the caller provides the given roles."""

    def dependency(
        principal: AuthenticatedPrincipal = Depends(authenticate_request),
    ) -> AuthenticatedPrincipal:
        principal.require_roles(roles, any_of=any_of)
        return principal

    return dependency


def reset_security_state() -> None:
    """Clear cached authentication configuration (useful for tests)."""

    global _api_key_scheme, _api_secret_scheme
    get_security_settings.cache_clear()
    if hasattr(get_credential_store, "cache_clear"):
        get_credential_store.cache_clear()
    _api_key_scheme = _build_api_key_header()
    _api_secret_scheme = _build_api_secret_header()


def create_protected_router(
    *, roles: Sequence[str] | None = None, any_of: bool = True
) -> APIRouter:
    """Create an ``APIRouter`` guarded by the authentication backend."""

    from fastapi import APIRouter

    dependencies = [Depends(authenticate_request)]
    if roles:
        dependencies = [Depends(require_roles(*roles, any_of=any_of))]
    return APIRouter(dependencies=dependencies)


__all__ = [
    "API_KEY_HEADER_ENV",
    "API_SECRET_HEADER_ENV",
    "AuthenticatedPrincipal",
    "CREDENTIALS_ENV",
    "CREDENTIALS_FILE_ENV",
    "CredentialStore",
    "ROLE_INGEST_READ",
    "ROLE_RENDER_MANAGE",
    "ROLE_RENDER_READ",
    "ROLE_RENDER_SUBMIT",
    "ROLE_REVIEW_READ",
    "authenticate_request",
    "create_protected_router",
    "get_credential_store",
    "get_security_settings",
    "require_roles",
    "reset_security_state",
]
