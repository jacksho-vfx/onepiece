# Ftrack client primer

The :mod:`libraries.ftrack` package contains a lightweight REST client that
shares the ergonomics of the existing ShotGrid helpers while targeting the
Ftrack API.  It provides:

* a thin authentication-aware :class:`~libraries.ftrack.client.FtrackRestClient`
  with helpers for issuing GET/POST requests;
* pydantic models describing commonly accessed entities such as projects,
  shots and tasks; and
* stub workflow methods to be filled in by future tasks.

## Quick start

```python
from libraries.ftrack import FtrackRestClient

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
:meth:`libraries.ftrack.client.FtrackRestClient.ensure_project` are defined but
raise :class:`NotImplementedError` to make the expected extension points
explicit.

During tests you can inject a stub :class:`requests.Session` to avoid real HTTP
calls while still exercising the request building and parsing logic.
