# Pipeline CLI Workflow

The `onepiece pipeline` command group provides tools for managing Trafalgar
pipeline definitions from the command line. The new manifest-aware commands are
ideal for synchronising local configuration files with either the in-process
orchestrator or a remote Trafalgar deployment.

## Command overview

| Command | Summary | Output formats |
| --- | --- | --- |
| `list` | Show registered pipeline definitions. | `text` (default), `json` via `--format`. |
| `describe` | Display a single pipeline definition. | `text`, `json` |
| `templates` | List bundled starter templates. | `text`, `json` |
| `scaffold` | Write a template manifest to disk. | `text` |
| `enable` | Re-enable a disabled pipeline. | `text`, `json` |
| `disable` | Prevent a pipeline from running. | `text`, `json` |
| `runs` | List recorded pipeline runs. | `text`, `json` |
| `rerun` | Trigger a new run from stored parameters. | `text`, `json` |
| `stats` | Summarise run outcomes across pipelines. | `text`, `json` |
| `prune` | Apply run retention policies and report removals. | `text`, `json` |
| `run-status` | Inspect metadata for a specific run. | `text`, `json` |
| `run-events` | Show recorded events for a pipeline run. | `text`, `json` |
| `workers` | Inspect current worker pool utilisation. | `text`, `json` |

Pass `--format json` to any of these commands to emit prettified JSON payloads,
which is useful when scripting against the CLI. The default `text` format
retains the human-readable summaries shown throughout this guide.

## Scaffolding a pipeline from a template

Start with a bundled template and tweak the commands to match your studio:

```bash
onepiece pipeline templates
onepiece pipeline scaffold starter.ingest_review manifests/ingest_review.toml
```

The scaffolds use the built-in `shell` and `noop` step factories so you can keep
the manifest structure while swapping in your own commands or Python providers.

## Triggering pipeline runs

Trigger executions with `onepiece pipeline run <pipeline-name>`. Supply
`--param key=value` pairs to forward ad-hoc parameters to the orchestrator.
When runs require complex payloads, provide `--params-file <path>` with a JSON
or TOML document instead. The CLI merges file-sourced parameters with any
`--param` overrides, allowing simple strings to replace nested structures from
the document when necessary.

```bash
onepiece pipeline run orchestration.daily \
  --params-file params/daily.json \
  --param ingest_profile=override
```

The parameters file must contain a mapping at the top level. Nested objects and
arrays are preserved so that downstream providers receive the full structure.

Disabled pipelines are rejected before they enter the run queue. If `run`
returns a message like "pipeline 'render_shots' is disabled", administrators can
re-enable the definition with `onepiece pipeline enable render_shots`. The
updated definition is written back to the orchestrator immediately and the
pipeline can accept new runs again.

When inspecting run outcomes with `onepiece pipeline stats`, supply
`--pipeline <name>` to focus on a single pipeline. The CLI validates the name
locally and forwards it to either the in-process orchestrator or the Trafalgar
API, so the aggregated counts (and optional duration metrics) only reflect runs
for that pipeline. Omit the flag to keep the existing behaviour of reporting on
every registered pipeline.

## Rerunning pipeline executions

The `rerun` command triggers a fresh execution from a stored definition
snapshot. Provide the original run identifier and optional parameter overrides:

```bash
onepiece pipeline rerun abc123 \
  --param shot=SQ02 \
  --param quality=ultra
```

Overrides replace values from the original run while retaining defaults defined
on the pipeline. The CLI also accepts `--params-file` and `--wait` flags with
the same behaviour as `onepiece pipeline run`, allowing operators to stream
events until the rerun succeeds or fails. When targeting a remote Trafalgar API
the command issues a `POST /runs/{run_id}/rerun` request using the caller's
credentials, ensuring audit trails reflect who initiated the new execution.

## Preparing a manifest

Create a TOML or YAML manifest that matches the format consumed by the
Trafalgar tools. The manifest must declare the pipeline name and at least one
step. For example, you can reference built-in `shell` or `noop` steps while
you iterate locally. For example:

```toml
name = "daily-render"

[[steps]]
id = "prepare"
uses = "package.pipeline:prepare"

[[steps]]
id = "render"
uses = "package.pipeline:render"
after = "prepare"
```

Multiple pipelines can be bundled in a single file via a top-level `pipelines`
section. When doing so, pass `--name` to select the entry to push or update.

## Validating manifests before pushing

Use `trafalgar pipeline validate <path>` to confirm a manifest meets the schema
before registering it. The command reports contextual errors that identify the
pipeline entry and the source file so you can fix typos quickly.

Validate a single TOML manifest:

```bash
trafalgar pipeline validate manifests/render.toml
```

When the manifest bundles multiple definitions under `pipelines`, the command
validates all entries and lists their names in the success output. Supply
`--name` to target a specific pipeline without evaluating the others:

```bash
trafalgar pipeline validate manifests/all-pipelines.toml
trafalgar pipeline validate manifests/all-pipelines.toml --name orchestrator
```

## Pulling existing definitions

Use `onepiece pipeline pull` to serialise a definition from the orchestrator back
to a manifest file. The command reconstructs step metadata, dependencies, and
event triggers so the resulting TOML or YAML can be fed straight into
`onepiece pipeline push` or `onepiece pipeline update`.

```bash
onepiece pipeline pull orchestration.daily --output manifests/orchestration.toml
```

The format is inferred from the file suffix, but you can override it explicitly:

```bash
onepiece pipeline pull orchestration.daily \
  --output manifests/orchestration.yaml \
  --format yaml
```

Once exported you can edit the manifest locally and push it back to the
orchestrator, closing the loop:

```bash
onepiece pipeline pull orchestration.daily --output tmp/orchestration.toml
# ...modify tmp/orchestration.toml...
onepiece pipeline update tmp/orchestration.toml
```

## Creating or updating pipelines

Use `onepiece pipeline push` to create a new pipeline definition. The command
validates the manifest with the same loader used by the Trafalgar CLI and then
invokes the configured pipeline API client.

```bash
onepiece pipeline push manifests/render.toml
```

If the pipeline already exists, prefer `onepiece pipeline update`, which sends a
`PUT /pipelines/{name}` request (or calls the local orchestrator equivalent):

```bash
onepiece pipeline update manifests/render.toml
```

Both commands provide clear error messages when the manifest is invalid or when
API responses indicate a conflict.

### Enabling and disabling pipelines

Operational teams can pause orchestration work without deleting definitions by
disabling the pipeline:

```bash
onepiece pipeline disable render_shots
```

The CLI confirms the change and subsequent `run` commands (or API requests) will
fail with a clear "pipeline is disabled" message. When it's time to resume, call
`onepiece pipeline enable render_shots` or target the REST API with a
`PATCH /pipelines/{name}` request containing `{ "enabled": true }`. The
`describe` and `list` commands annotate disabled definitions so operators can see
the status at a glance.

### Concurrent updates

Local orchestrator deployments persist pipeline definitions to JSON files on
disk. The definition store now acquires advisory file locks while reading and
writing those files, ensuring that parallel CLI commands or background services
cannot clobber updates. Locks are automatically released even if a process
crashes mid-write, and updates remain atomic thanks to the temporary-file swap
used beneath the lock.

### Tuning orchestrator concurrency

Operators running the in-process orchestrator can increase parallelism by adding
`pipeline.storage.max_workers` to their profile configuration. The CLI passes
this setting through `configure_orchestrator_from_profile`, allowing multiple
pipelines to execute at once when the backing storage can sustain the load.
Omitting the key keeps the previous single-worker behaviour or falls back to
`pipeline.workers.max` when defined.

For persistence layouts and retention options, consult
[`docs/configuration_profiles.md`](configuration_profiles.md#profilesnamepipelinestorage)
so CLI-driven deployments match the storage settings used in Trafalgar.

### Declaring parameter metadata

Pipeline manifests can expose strongly-typed run parameters. Add a
`parameters` table to the manifest and annotate each entry with the expected
metadata:

```toml
[parameters]
# default value stored as string; CLI/API coerce to integer at runtime
retries.type = "integer"
retries.default = "3"

[parameters.mode]
type = "string"
enum = ["auto", "manual"]
description = "Select execution mode for automation calls."
```

Supported `type` values are `string`, `integer`, `number`, and `boolean`.
Synonyms such as `str`, `int`, and `bool` are also accepted. The optional
`choices` (or legacy `enum`/`options`) field constrains a parameter to a set of
values and is validated after coercion. Defaults and run-time inputs are
converted to the declared type, so "3" becomes the integer 3, "yes" turns into
`True`, and invalid values raise actionable errors.

`onepiece pipeline list` and `onepiece pipeline describe` now display the type
and choice metadata alongside the usual default/required summaries. The
`--format json` payloads (and Trafalgar's REST API) include the same `type` and
`choices` fields so dashboards and automation jobs can surface friendly pickers
or form validation.

### Monitoring worker capacity

The worker pool metrics endpoint provides quick visibility into how busy the
orchestrator is. Run `onepiece pipeline workers` to fetch the latest snapshot:

```bash
onepiece pipeline workers
# Active workers: 2 (limit: 6).
```

Supply `--format json` when feeding the metrics into monitoring dashboards or
automation jobs. When targeting a remote Trafalgar deployment, the CLI proxies
the `GET /workers/metrics` API with the same authentication headers that power
other pipeline commands.

### Inspecting run event history

Historical run events are available from both the CLI and the Trafalgar API. Use
`onepiece pipeline run-events <run-id>` to render the recorded events for a
pipeline run. The default text output mirrors the formatting of
`onepiece pipeline watch`, while `--format json` exposes the raw event payloads.

When integrating with other services directly, call the REST endpoint
`GET /runs/{run_id}/events/history`. The route shares the same authentication
requirements as the live event stream (`GET /runs/{run_id}/events`) and responds
with an array of serialised events. This makes it easy to fetch the final state
of a run after it has completed or to replay granular step updates for audit
purposes.

## Deleting pipelines

To remove a pipeline definition, call:

```bash
onepiece pipeline delete daily-render
```

The command reports `Unknown pipeline` errors as argument validation problems so
that they can be handled interactively.

## Pruning pipeline run history

Use `onepiece pipeline prune` to apply retention settings to the run store on
command. The CLI invokes either the in-process orchestrator or the configured
remote API and then displays the returned summary.

```bash
onepiece pipeline prune --max-age-hours 48 --max-runs 250
```

Both options are optional:

- `--max-age-hours` prunes runs created before the configured number of hours
  ago. Fractional values are accepted (for example `1.5` for ninety minutes).
- `--max-runs` retains only the newest runs up to the supplied limit after the
  prune completes.

Omit both flags to use the retention policy configured in Trafalgar. Pair the
command with `--format json` when piping the summary into automation tools.

## Provider execution context

Pipeline providers invoked by the orchestrator now receive a
`StepExecutionContext` describing the current run. Sequential providers should
accept `(context, parameters)` while event-driven providers should accept
`(context, event, parameters)`. Existing two-argument callables continue to work
without modification; the executor adapts legacy `(parameters)` and
`(event, parameters)` functions automatically.

The context exposes:

- `run_id` – unique identifier for the active pipeline run.
- `pipeline_name` – the name of the pipeline definition executing.
- `step_name` – the step currently being evaluated.
- `metadata` – a mapping containing `pipeline` and `step` metadata snapshots.
- `parameters` – the resolved parameter mapping for the run.

Use the context to avoid recomputing metadata lookups and to attach run-aware
diagnostics or payloads to downstream systems.
