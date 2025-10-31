# Pipeline CLI Workflow

The `onepiece pipeline` command group provides tools for managing Trafalgar
pipeline definitions from the command line. The new manifest-aware commands are
ideal for synchronising local configuration files with either the in-process
orchestrator or a remote Trafalgar deployment.

## Preparing a manifest

Create a TOML or YAML manifest that matches the format consumed by the
Trafalgar tools. The manifest must declare the pipeline name and at least one
step. For example:

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

## Deleting pipelines

To remove a pipeline definition, call:

```bash
onepiece pipeline delete daily-render
```

The command reports `Unknown pipeline` errors as argument validation problems so
that they can be handled interactively.
