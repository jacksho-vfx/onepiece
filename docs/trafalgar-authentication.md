# Trafalgar Service Authentication

The Trafalgar APIs (render, ingest, and review) are protected by a shared
authentication backend that accepts either signed API key/secret pairs or
OAuth2 bearer tokens. The same dependency stack is used across all services so
operators only need to provision credentials once.

> **Release spotlight (v1.0.0):** Render job inspection and cancellation endpoints now
> check for the `render:manage` role, the dashboard cache administration routes reuse
> the bearer token flow, and the embedded Uta dashboard honours the same credentials
> when proxied through the browser UI.

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

## Testing credentials locally

Launch the Trafalgar services with temporary credentials to validate new
integrations before sharing them:

```bash
export TRAFALGAR_SERVICE_CREDENTIALS='[
  {"id": "local-render", "key": "demo-key", "secret": "demo-secret", "roles": ["render:read", "render:submit"]}
]'

onepiece trafalgar web render --host 127.0.0.1 --port 8001
```

Then call the API with matching headers:

```bash
curl -H "X-API-Key: demo-key" -H "X-API-Secret: demo-secret" \
  http://127.0.0.1:8001/render/farms
```

Switch to bearer tokens by setting `TRAFALGAR_SERVICE_CREDENTIALS` with a
`token` entry and passing `Authorization: Bearer <token>`.

## Troubleshooting

- **`401 Unauthorized`** – The token or key/secret pair did not match a known
  credential, or the request omitted the required headers. Confirm the header
  names align with `TRAFALGAR_API_KEY_HEADER`/`TRAFALGAR_API_SECRET_HEADER` and
  that the credential entry is loaded.
- **`403 Forbidden`** – Authentication succeeded but the credential lacks the
  necessary role. Review the role list in the configuration and add the missing
  permission (for example `render:manage` for cancellation requests).
- **`503 Service Unavailable`** – The service could not load credentials during
  startup. Check the log output for JSON parsing errors or missing files and
  ensure at least one credential is configured.

## CLI integration

The OnePiece CLI forwards Trafalgar credentials automatically when environment
variables are set. For example, running

```bash
export TRAFALGAR_API_KEY_HEADER=X-API-Key
export TRAFALGAR_API_SECRET_HEADER=X-API-Secret
export TRAFALGAR_SERVICE_CREDENTIALS='[{"id": "cli", "key": "cli-key", "secret": "cli-secret", "roles": ["render:submit"]}]'

onepiece render submit --farm mock --scene shots/shot.ma --frames 1001-1012 \
  --output renders/shot
```

ensures the CLI's HTTP requests include the correct headers. When operating with
bearer tokens, set `TRAFALGAR_DASHBOARD_TOKEN` and the CLI will attach the
`Authorization` header automatically for dashboard and render requests.
