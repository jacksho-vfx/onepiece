# OnePiece pipeline CLI and orchestrator

> **At a glance**
>
> - [Command entry points](#command-entry-points) — Where to interact with the
>   orchestrator today and how the OnePiece CLI will hook in.
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

The `onepiece pipeline` command group ships as a placeholder so automation can
stabilise around the command surface before the orchestrator client lands.
Every command currently prints actionable guidance reminding you to connect the
action to the orchestrator once the API is available. 【F:src/apps/onepiece/pipeline/__init__.py†L1-L53】

Until the OnePiece CLI integrates directly with the orchestrator, use the
Trafalgar CLI to list definitions and trigger runs:

```console
$ trafalgar pipeline list
orchestration.daily (Daily orchestration pipeline)
  Parameters: ingest_profile, notify_channel

$ trafalgar pipeline run orchestration.daily --param ingest_profile=episodic
Triggered pipeline 'orchestration.daily' (run id: 5e2fd4a5...).
Current status: succeeded
```

The Trafalgar helper pulls definitions from the shared orchestrator instance
and accepts repeated `--param key=value` flags that are parsed into a mapping
before the run is triggered. Invalid parameter syntax produces a
Typer-friendly error so CI pipelines can fail fast. 【F:src/apps/trafalgar/app.py†L1-L120】

On the web side, the `/pipeline` FastAPI application mirrors the same
operations. Callers with the `pipeline:read` role can enumerate definitions and
query run metadata, while `pipeline:run` is required to trigger new runs.
Streaming `/pipeline/runs/{id}/events` returns a server-sent event feed that is
ideal for dashboards and chatbots. 【F:src/apps/trafalgar/web/pipeline.py†L1-L120】

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
