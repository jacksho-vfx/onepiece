# OnePiece configuration profiles

The `onepiece` CLI discovers configuration profiles from multiple locations to
provide defaults for commands like `aws ingest`. Profiles are defined in
`onepiece.toml` files and merged in the following order (lowest precedence
first):

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
