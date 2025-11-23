# OnePiece configuration profiles

> **Documentation refresh (November 2025):** Profile discovery details now ship with quick links to the most referenced sections and the environment variables that influence merging behaviour. Use the outline below to jump directly to the resolution tier you need to audit.

## At a glance

- [Resolution order](#onepiece-configuration-profiles) — Review how user, project, and workspace files merge.
- [Environment overrides](#environment-variable-overrides) — Confirm which variables redirect profile discovery.
- [Recommended keys](#recommended-profile-keys) — Reference the canonical options used throughout the CLI examples.

The `onepiece` CLI discovers configuration profiles from multiple locations to
provide defaults for commands like `aws ingest`. Profiles are defined in
`onepiece.toml` files and merged in the following order (lowest precedence
first): 【F:src/apps/onepiece/config.py†L1-L120】

> **Release spotlight (v1.0.0):** Profile resolution now includes workspace-level overrides, the active profile can be inspected with `onepiece profile`, and ingest commands honour new keys for resumable uploads, checkpoint tuning, and asyncio orchestration.

1. **User configuration** – files located at:
   - `$XDG_CONFIG_HOME/onepiece/onepiece.toml` when `XDG_CONFIG_HOME` is set.
   - `~/.config/onepiece/onepiece.toml`
   - `~/.onepiece/onepiece.toml`
   - `~/onepiece.toml`
2. **Project configuration** – files located at either
   `<project-root>/onepiece.toml` or `<project-root>/.onepiece/onepiece.toml`.
   The project root defaults to the current working directory but can be
   overridden with the `ONEPIECE_PROJECT_ROOT` environment variable.
3. **Workspace configuration** – a `onepiece.toml` file stored inside the
   workspace folder that a command operates on (for example, the delivery folder
   passed to `onepiece aws ingest`).
4. **Command line arguments** – explicit options always override profile values.

Later files override earlier ones using deep-merge semantics, so a workspace
profile can change only a subset of values defined by the project or user
profiles.

Each configuration file can optionally define a `default_profile` key to select
which profile should be used when the CLI is invoked without `--profile`. The
value from the highest precedence file that specifies it wins. Profiles are
stored beneath the `[profiles]` table and may include general keys (such as
`project` and `show_code`) as well as command-specific tables like
`[profiles.mystudio.ingest]`:

```toml
default_profile = "mystudio"

[profiles.mystudio]
project = "Studio Project"
show_code = "STUDIO"
vendor_bucket = "vendor_in"
client_bucket = "client_in"

[profiles.mystudio.ingest]
max_workers = 8
resume = true
checkpoint_dir = "~/uploads/checkpoints"
```

When `onepiece aws ingest` runs, the CLI resolves the active profile using the
search order above, applies any overrides provided on the command line, and
passes the merged configuration to the ingest service. Other commands can reuse
these utilities to obtain consistent profile data.

## Environment variable overrides

These environment variables influence where configuration files are discovered or how profiles are merged:

| Variable | Purpose |
| --- | --- |
| `ONEPIECE_PROJECT_ROOT` | Overrides the root used to locate project-level `onepiece.toml` files. |
| `ONEPIECE_PROFILE` | Forces a specific profile name when running commands that accept `--profile`. |
| `ONEPIECE_PROFILE_SOURCES` | Comma-separated list of additional directories to scan for `onepiece.toml` files. |

Set them in your shell profile when working across multiple shows or when you need to pin a workstation to a known configuration snapshot.

## Related Trafalgar dashboard configuration

Environment variables that influence the Trafalgar dashboard runtime—such as
cache TTLs, capacity limits, and admin endpoints—are documented in
[`docs/dashboard_api.md`](./dashboard_api.md#dashboard-caching-controls). Review
those settings alongside your profile files so deployment guides surface the
operational levers available to operators.

## Inspecting merge output

Run `onepiece profile --show-sources` to see exactly where each value comes
from. The CLI prints a table similar to the following so you can debug
unexpected overrides:

```
Profile: mystudio (resolved)

┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Key            ┃ Value                                      ┃ Source       ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ project        │ Studio Project                             │ user.toml    │
│ show_code      │ STUDIO                                     │ project.toml │
│ vendor_bucket  │ vendor_in                                  │ workspace    │
│ ingest.resume  │ True                                       │ workspace    │
│ ingest.max_workers │ 8                                      │ CLI          │
└────────────────┴────────────────────────────────────────────┴──────────────┘
```

Values supplied on the command line are rendered in bold and flagged with the
`CLI` source, making it clear when ad-hoc overrides are active.

## Recommended keys

Profiles may contain arbitrary keys; the following tables capture the common
sections consumed by first-party commands.

### Top-level keys

| Key | Description |
| --- | --- |
| `project` | Human-readable project name surfaced in reports and manifests. |
| `show_code` | Short code used when naming S3 prefixes, delivery folders, and playlists. |
| `vendor_bucket` / `client_bucket` | Default S3 buckets for ingest workflows. |
| `profile_notes` | Free-form notes that appear when running `onepiece profile`. |

### `[profiles.<name>.ingest]`

| Key | Description |
| --- | --- |
| `max_workers` | Thread pool size for uploads. |
| `resume` | Enable resumable uploads and checkpoint persistence. |
| `checkpoint_dir` | Location on disk where multipart checkpoints are stored. |
| `checkpoint_threshold` | Minimum file size (bytes) before checkpoints are written. |
| `upload_chunk_size` | Multipart chunk size (bytes) used when resuming transfers. |
| `use_asyncio` | Toggle asyncio orchestration for I/O-bound workloads. |

### `[profiles.<name>.pipeline.storage]`

| Key | Description |
| --- | --- |
| `database` / `path` | Location of the SQLite database backing pipeline run history. |
| `definitions` / `definitions_path` | Directory where pipeline definitions are serialised so the orchestrator can reload them across restarts. |
| `busy_timeout` / `busy_timeout_ms` | Optional overrides for SQLite's busy timeout while persisting events. |
| `retention` | Mapping that constrains how much historical run data is retained. |
| `max_workers` | Number of concurrent pipelines the orchestrator executes when storage-backed persistence is enabled. |

Configure this section when you want the embedded orchestrator (or the CLI acting
as a daemon) to persist run state between restarts. The `database` key accepts a
filesystem path and ensures parent directories are created automatically. Use
`path` as a backwards-compatible alias when migrating older profile files.

Adding `definitions` (or `definitions_path`) points the orchestrator at a folder
to mirror the active pipeline definitions. Local pushes atomically update the
JSON files in that directory so subsequent CLI calls or services can reload the
latest steps without re-registering them by hand.

The optional `busy_timeout` value raises SQLite's lock wait window (seconds by
default, or milliseconds via `busy_timeout_ms`). Increase it on shared NAS or
network volumes to avoid transient `database is locked` errors when multiple
workers emit run events at once.

Retention settings provide guard rails for long-lived deployments. Populate the
`retention` table to prune runs based on age or total volume. The orchestrator
skips pruning when the mapping is empty.

#### `pipeline.storage.retention`

| Key | Description |
| --- | --- |
| `max_runs` | Upper bound on the total number of runs kept in the store. |
| `seconds` / `minutes` / `hours` / `days` | Choose a single duration key to cap run age; values are converted to seconds. |
| `pipelines.<name>.max_runs` | Override `max_runs` for a specific pipeline. Set per entry inside the `pipelines` table. |

Example configuration persisting run history and definitions to disk:

```toml
[profiles.mystudio.pipeline.storage]
database = "/var/lib/onepiece/pipelines.sqlite3"
definitions = "/var/lib/onepiece/pipeline-definitions"
busy_timeout = 10

[profiles.mystudio.pipeline.storage.retention]
days = 14
max_runs = 500

[profiles.mystudio.pipeline.storage.retention.pipelines.render]
max_runs = 50
```

### `[profiles.<name>.render]`

| Key | Description |
| --- | --- |
| `farm` | Default render farm adapter name (for example `mock` or `tractor`). |
| `priority` | Preferred priority passed to the adapter unless overridden. |
| `chunk_size` | Frame chunking default that respects adapter limits. |
| `user` | Submitter identifier used when the CLI does not infer it automatically. |
| `output_root` | Root directory where frame outputs should be written. |

### `[profiles.<name>.notify]`

| Key | Description |
| --- | --- |
| `email_recipients` | List of email addresses for the `notify email` command. |
| `slack_channel` | Default Slack channel or webhook for `notify slack`. |
| `include_reports` | Boolean flag controlling whether reports are attached automatically. |

Use these tables as a checklist when onboarding new shows or departments so the
CLI behaves consistently across teams.
