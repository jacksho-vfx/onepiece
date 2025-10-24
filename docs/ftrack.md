# Ftrack client primer

The :mod:`libraries.integrations.ftrack` package contains a lightweight REST client that
shares the ergonomics of the existing ShotGrid helpers while targeting the
Ftrack API.  It provides:

* a thin authentication-aware :class:`~libraries.integrations.ftrack.client.FtrackRestClient`
  with helpers for issuing GET/POST requests;
* pydantic models describing commonly accessed entities such as projects,
  shots and tasks; and
* stub workflow methods to be filled in by future tasks.

## Quick start

```python
from libraries.integrations.ftrack import FtrackRestClient

client = FtrackRestClient(
    base_url="https://my.ftrack.server",
    api_user="pipeline_bot",
    api_key="super-secret",
)

projects = client.list_projects()
print(projects[0].name)
```

The list helpers return instances of the pydantic models so calling code gets
runtime validation for free.  Higher-level convenience methods such as
:meth:`libraries.integrations.ftrack.client.FtrackRestClient.ensure_project` are defined but
raise :class:`NotImplementedError` to make the expected extension points
explicit.

During tests you can inject a stub :class:`requests.Session` to avoid real HTTP
calls while still exercising the request building and parsing logic.

## Authentication helpers

The client supports both API key and OAuth token authentication. Constructing
the client with `api_user` and `api_key` enables request signing, while
providing a pre-issued bearer token sets the `Authorization: Bearer` header for
each request.

```python
client = FtrackRestClient(
    base_url="https://my.ftrack.server",
    bearer_token=os.environ["FTRACK_BEARER_TOKEN"],
)
```

Use the `libraries.integrations.ftrack.auth.load_credentials` helper to read credentials from
environment variables or JSON files—mirroring the Trafalgar authentication
workflow—so workstation scripts and automation jobs behave consistently.

## Usage patterns

- **Project discovery** – `client.list_projects(status="active")` returns a
  paginated iterator of `Project` models that expose `id`, `name`, `status`, and
  date metadata.
- **Shot lookup** – `client.get_shot(project_id, sequence_code, shot_code)`
  collapses the REST queries needed to traverse the project hierarchy.
- **Task creation** – `client.ensure_task(project_id, entity_id, task_type)`
  creates the task if it is missing and returns the resulting model so callers
  can link versions immediately.

All helpers surface HTTP errors via rich exceptions that include the URL,
status code, and response payload, making it easy to log structured error data.

## CLI integration

A dedicated CLI surface has not shipped yet. Until it does, embed the
`FtrackRestClient` directly inside automation scripts or Typer commands. The
client is intentionally thin so wiring it into a future `onepiece ftrack`
command group or a bespoke deployment-specific tool requires minimal effort.
Follow the patterns in the ShotGrid helpers when authoring CLI wrappers: accept
credentials via environment variables, reuse the shared `structlog`
configuration, and raise `typer.BadParameter` for validation errors so the user
experience mirrors the existing command groups. 【F:src/apps/onepiece/utils/errors.py†L1-L120】【F:src/libraries/integrations/ftrack/client.py†L1-L211】
