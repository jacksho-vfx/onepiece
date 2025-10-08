# Trafalgar Service Authentication

The Trafalgar APIs (render, ingest, and review) are protected by a shared
authentication backend that accepts either signed API key/secret pairs or
OAuth2 bearer tokens. The same dependency stack is used across all services so
operators only need to provision credentials once.

## Configuration

Credentials are loaded at runtime from either an environment variable or a JSON
file. Two environment variables control the sources:

| Variable | Description |
| --- | --- |
| `TRAFALGAR_SERVICE_CREDENTIALS` | Inline JSON payload describing credentials. |
| `TRAFALGAR_SERVICE_CREDENTIAL_FILE` | Path to a JSON file with the same schema. |

Both sources can be used simultaneously; entries from the environment are
merged with those read from disk. Each credential entry must contain a unique
`id` plus either an API `key` (with optional `secret`) or a bearer `token`. A
minimal example looks like:

```json
[
  {
    "id": "render-cli",
    "key": "render-service-key",
    "secret": "render-service-secret",
    "roles": ["render:read", "render:submit", "render:manage"]
  },
  {
    "id": "review-automation",
    "token": "oauth-access-token",
    "roles": ["review:read"]
  }
]
```

Header names are configurable via `TRAFALGAR_API_KEY_HEADER` (defaults to
`X-API-Key`) and `TRAFALGAR_API_SECRET_HEADER` (defaults to `X-API-Secret`).
Bearer tokens must be supplied using the standard `Authorization: Bearer …`
header.

### Roles

Role strings gate access to logical operations:

* `render:read` — list farms, inspect jobs, stream status updates, health checks.
* `render:submit` — create render jobs.
* `render:manage` — cancel render jobs.
* `ingest:read` — read ingest history, subscribe to ingest events, ingest health.
* `review:read` — list and inspect review playlists.

The dependency helpers enforce these roles per route. Credentials can declare
multiple roles when a client needs to access more than one workflow.

## Onboarding Workflow

1. Generate a random API key and (optionally) secret for the new integration.
   Use a minimum of 32 random bytes and base64-encode them.
2. Decide which roles the client requires and add them to the credential entry.
3. Update `TRAFALGAR_SERVICE_CREDENTIALS` (or the configured JSON file) with the
   new entry. If you edit a file in source control, ensure it is encrypted or
   stored in a secret manager.
4. Reload the affected FastAPI service so the credential cache is refreshed.
   During tests you can call `apps.trafalgar.web.security.reset_security_state()`.
5. Share the key/secret pair with the client through an existing secure channel
   (e.g. password manager or vault). Remind integrators to send the key via
   `X-API-Key` and the secret via `X-API-Secret`.

For OAuth2 clients, onboard them with the upstream identity provider and record
the resulting access token (or client credentials) in the same configuration.

## Rotation Procedure

1. Provision a replacement credential entry with the same roles as the current
   one. Keep both active during the overlap period so clients can switch without
   downtime.
2. Notify integrators of the new key/secret or token and confirm they have
   rotated their configuration.
3. Remove the old entry from the configuration and reload the services.
4. Audit the application logs — `security.credentials` warnings indicate parsing
   issues and `*.authentication` events should disappear once the old credential
   is removed.

Because credentials are cached, any configuration change requires a service
restart (or an explicit cache reset during tests). Document the rotation time
and the associated change request for traceability.
