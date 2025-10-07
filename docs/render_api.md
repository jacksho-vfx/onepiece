# Render API capability schema

The Trafalgar render service exposes the `/farms` endpoint so CLI tools and UI
widgets can discover registered adapters along with the behaviour they support.
The response now returns structured capability descriptors for each adapter.

```json
{
  "farms": [
    {
      "name": "mock",
      "description": "Mock render farm for testing and demos.",
      "capabilities": {
        "priority": {
          "default": 50,
          "minimum": 0,
          "maximum": 100
        },
        "chunking": {
          "enabled": true,
          "minimum": 1,
          "maximum": 10,
          "default": 5
        },
        "cancellation": {
          "supported": false
        }
      }
    }
  ]
}
```

The descriptors can be interpreted as follows:

- `priority` – documents the default priority applied by the service when a
  submission omits one, along with the adapter's minimum and maximum allowed
  range. Values outside this range are rejected by the CLI and API.
- `chunking` – indicates whether the adapter supports frame chunking and, when
  enabled, the allowed range plus the default chunk size. Clients should hide or
  disable chunk controls when `enabled` is `false`.
- `cancellation` – signals whether the adapter implements the cancellation hook
  consumed by the job management endpoints. Interfaces can conditionally expose
  cancel buttons based on this flag.

These descriptors align with the validation logic used by the CLI
(`python -m apps.onepiece render submit`) so interactive tools can surface the
same guard rails and defaults without reaching into adapter internals.
