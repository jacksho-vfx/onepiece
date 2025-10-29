# OnePiece pipeline CLI and orchestrator

> **At a glance**
>
> - [Command entry points](#command-entry-points) — Where to interact with the
>   orchestrator today and how the OnePiece CLI will hook in.
> - [Pipeline storage](#pipeline-storage) — Configure the SQLite backend that
>   records pipeline runs and events.
> - [Loading pipeline definitions](#loading-pipeline-definitions) — Surface
>   named pipelines alongside configuration profiles.
> - [Factory utilities](#factory-utilities) — Convert mappings into strongly
>   validated pipeline models and resolve providers.
> - [Extending steps via plugins](#extending-steps-via-plugins) — Publish custom
>   pipeline steps without forking OnePiece.
> - [Sample manifests and payloads](#sample-manifests-and-payloads) — Copy-ready
>   blueprints for sequential and event-driven automation.

The pipeline surface connects Typer command groups, configuration loaders, and
an in-memory orchestrator that Trafalgar exposes over both CLI and FastAPI
interfaces. This guide shows how those layers fit together so you can author
pipelines today and wire them into the orchestrator as the service hardens.

## Command entry points

The `onepiece pipeline` group is the primary interface for the orchestrator.
Each command reaches the in-process orchestrator by default and automatically
switches to the Trafalgar HTTP API whenever `ONEPIECE_PIPELINE_FORCE_REMOTE`
is set or a pipeline API URL environment variable is present. Use
`ONEPIECE_PIPELINE_FORCE_LOCAL` to pin the CLI to the embedded orchestrator even
when remote settings exist. 【F:src/apps/onepiece/pipeline/__init__.py†L56-L158】【F:src/apps/onepiece/pipeline/__init__.py†L256-L314】

Commands share a common parameter parser so repeated `--param key=value`
options become a dictionary that is forwarded to the orchestrator. Missing `=`
delimiters or blank keys raise a Typer validation error before the request is
sent. 【F:src/apps/onepiece/pipeline/__init__.py†L208-L244】【F:src/apps/onepiece/pipeline/__init__.py†L340-L410】

- `onepiece pipeline list` prints every registered definition, including human
  friendly names and the parameter keys exposed by each pipeline.
- `onepiece pipeline describe <name>` expands the metadata for a specific
  definition, echoing descriptions and parameter defaults.
- `onepiece pipeline run <name> --param key=value` triggers a run and returns
  the assigned identifier plus the orchestrator-reported status.
- `onepiece pipeline runs` filters historical runs with `--pipeline`,
  `--status`, `--since` (ISO timestamp), and `--limit` arguments.
- `onepiece pipeline run-status <run-id>` shows detailed metadata for a single
  run, mirroring the list output.
- `onepiece pipeline watch <run-id>` tails live status events until the run
  settles. Remote transports stream the Trafalgar `/runs/{id}/events` endpoint,
  while local transports proxy the in-memory async iterator. 【F:src/apps/onepiece/pipeline/__init__.py†L316-L520】【F:src/apps/onepiece/pipeline/__init__.py†L158-L205】

```console
$ onepiece pipeline list
orchestration.daily (Daily orchestration pipeline)
  Parameters: ingest_profile, notify_channel

$ onepiece pipeline describe orchestration.daily
Name: orchestration.daily
Display name: Daily orchestration pipeline
Description: Mirrors ingest payloads and posts delivery updates.
Parameters:
  - ingest_profile: episodic
  - notify_channel: #dailies

$ onepiece pipeline run orchestration.daily --param ingest_profile=episodic \
    --param notify_channel="#dailies"
Triggered pipeline 'orchestration.daily' (run id: 5e2fd4a5...).
Current status: running

$ onepiece pipeline run-status 5e2fd4a5...
Run 5e2fd4a5...
  Pipeline: orchestration.daily
  Status: succeeded
  Created: 2024-05-12T10:03:11+00:00
  Updated: 2024-05-12T10:03:27+00:00

$ onepiece pipeline watch 5e2fd4a5...
[2024-05-12T10:03:11+00:00] orchestration.daily - queued
[2024-05-12T10:03:12+00:00] orchestration.daily - running
  Step: ingest
  Trigger event: asset.uploaded
  Trigger payload: {"asset_id": "a123", "retry": false}
[2024-05-12T10:03:18+00:00] orchestration.daily - step_succeeded
  Step: ingest
[2024-05-12T10:03:27+00:00] orchestration.daily - succeeded
```

## Pipeline storage

Trafalgar persists run metadata to a SQLite database through
`PipelineRunStore`. When the store connects to an on-disk database it enables
Write-Ahead Logging (WAL) mode and applies a five second busy timeout so
multiple workers can enqueue events without tripping SQLite's
`OperationalError: database is locked` guard. Both options carry over to new
connections so parallel API workers or CLI processes can share the same file
without juggling manual pragmas. 【F:src/apps/trafalgar/pipeline.py†L151-L187】

Profiles expose a `[pipeline.storage]` table so deployments can select a custom
path and tune the locking window when higher write volume demands it. Supply a
`busy_timeout` in seconds or `busy_timeout_ms` in milliseconds alongside the
database location:

```toml
[profiles.production.pipeline.storage]
database = "/srv/onepiece/pipelines.sqlite3"
busy_timeout = 7.5  # seconds (or use busy_timeout_ms = 7500)
```

The orchestrator validates that only one timeout key is present and falls back
to the default when no override is supplied. In-memory stores remain available
for tests or ephemeral runners by omitting the table entirely. 【F:src/apps/trafalgar/pipeline.py†L577-L593】

## Loading pipeline definitions

Named pipelines now live alongside profile data in `onepiece.toml`. The
configuration loader returns a `ProfileContext` object that exposes the resolved
profile name, merged settings, the source files that participated in the merge,
and a mapping of pipeline metadata keyed by name. Pipeline entries are surfaced
as plain dictionaries so callers can adapt them to their own schema or hand
them straight to the factory helpers documented below. 【F:src/apps/onepiece/config.py†L1-L120】【F:src/apps/onepiece/config.py†L180-L220】

```toml
[pipelines.orchestration.daily]
summary = "Daily ingest, conform, and review orchestration"
steps = [
  { name = "ingest", provider = "studio.pipeline.steps:ingest" },
  { name = "conform", provider = "studio.pipeline.steps:conform" },
]
```

```python
from apps.onepiece import config as config_module

context = config_module.load_profile(profile="episodic")
pipeline_config = context.pipelines["orchestration.daily"]
```

The `pipelines` mapping honours the same merge order as profile data (user →
project → workspace). Invalid tables raise `OnePieceConfigError` so mis-shaped
pipeline definitions surface immediately during bootstrap runs. 【F:src/apps/onepiece/config.py†L1-L120】

## Factory utilities

The `libraries.pipeline` module family converts configuration dictionaries into
validated models and resolves providers before orchestrator registration.
`pipeline_from_config` normalises dependency chains, enforces unique step names,
and ensures every referenced dependency exists. Call
`with_resolved_providers` to replace string references with callables using an
optional registry. 【F:src/libraries/pipeline/factories.py†L1-L120】

```python
from libraries.pipeline import factories

pipeline = factories.pipeline_from_config(pipeline_config)
resolved = factories.with_resolved_providers(
    pipeline,
    registry={"ingest": ingest_step_factory},
)
```

Under the hood each step is represented by a `PipelineStep` with an attached
`TriggerPolicy`. The models normalise sequential vs event-driven triggers,
standardise dependency lists, and reject missing names, providers, or
self-referential dependencies. Iterating `pipeline.sequential_order()` produces
just the sequential steps so you can enqueue work while ignoring event-driven
hooks. 【F:src/libraries/pipeline/models.py†L1-L160】【F:src/libraries/pipeline/models.py†L160-L260】

## Extending steps via plugins

Studios can register custom pipeline step factories through the
`onepiece.pipeline_steps` entry-point group. The discovery helper validates that
loaded factories are callable, prevents name collisions with built-in steps, and
raises dedicated exceptions when optional dependencies are missing. Use these
exceptions to print actionable install instructions back to operators. 【F:src/libraries/pipeline/plugins.py†L1-L120】

```toml
[project.entry-points."onepiece.pipeline_steps"]
delivery-qc = "studio.pipeline:delivery_qc_factory"
```

```python
from libraries.pipeline import factories as pipeline_factories, plugins

step_factories = plugins.discover_pipeline_step_factories(
    builtin={"ingest": ingest_factory}
)
pipeline = pipeline_factories.pipeline_from_config(pipeline_config)
resolved = pipeline_factories.with_resolved_providers(
    pipeline,
    registry=step_factories,
)
```

`MissingPipelineStepRequirementError` and `InvalidPipelineStepFactoryError`
include the offending entry-point name so CI logs and documentation can direct
teams towards the fix immediately. 【F:src/libraries/pipeline/plugins.py†L1-L120】

## Sample manifests and payloads

The `docs/examples/pipelines/` directory contains ready-made definitions for
sequential and event-driven automations. Pair the manifests with the matching
JSON payloads to simulate orchestrator runs locally or inside CI. Use them as a
starting point when shaping your own `onepiece.toml` pipelines or when
demonstrating the orchestrator to stakeholders. 【F:docs/examples/pipelines/linear/pipeline.yaml†L1-L40】【F:docs/examples/pipelines/event-driven/pipeline.yaml†L1-L80】

For a step-by-step walkthrough that ties the manifests back to CLI usage, see
[§13 in `docs/cli_walkthroughs.md`](cli_walkthroughs.md#13-bootstrap-pipelines-with-sample-manifests).
