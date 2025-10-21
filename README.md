# OnePiece

OnePiece is a Typer-powered command line toolkit designed for ingesting, packaging, and publishing media assets across digital content creation (DCC) tools and production tracking systems. It bundles high-level pipeline commands—such as AWS S3 synchronisation, ShotGrid setup utilities, and DCC publishing helpers—into a single CLI that can be embedded inside a studio workflow.

> **Platform release v1.0.0** aligns the OnePiece CLI, Trafalgar services, and the new Uta Control Center. The CLI now honours layered configuration profiles, adds resumable ingest controls, and validates render submissions against adapter capabilities. Trafalgar keeps the dashboard responsive with project discovery caches, admin-tunable TTLs, and render job management APIs. Uta introspects the CLI surface, renders it as an interactive web UI, and embeds the Trafalgar dashboard so supervisors can orchestrate pipelines from a browser.
>
> **Recent merges** extend the DCC tooling with a dedicated animation command group, an Unreal Engine importer, and tighter publish validation. Maya-specific helpers now guard against missing PyMEL installations, plugin discovery treats module names case-insensitively, and scene-name validation rejects unsafe paths. Trafalgar introduces a pluggable provider registry with sensible defaults so delivery and reconciliation data sources can be extended without forking the service.

## Quick start

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\\Scripts\\activate

# Install the CLI and its core dependencies
pip install -e .

# Explore the available commands
onepiece --help
perona --help
```

Once installed, the CLI exposes a number of subcommands:

- `onepiece info` &mdash; Prints information about the current environment, detected DCCs, and ShotGrid/AWS configuration hints.
- `onepiece profile` &mdash; Displays the resolved configuration profile, including the settings loaded from `onepiece.toml` files.
- `onepiece dcc publish ...` &mdash; Packages scene renders, previews, and metadata and pushes them to S3 (see the detailed options below).
- `onepiece dcc open-shot` &mdash; Launches a scene file in the matching DCC, automatically inferring the application from the file extension when not supplied explicitly.
- `onepiece dcc animation debug-animation|cleanup-scene|playblast` &mdash; Diagnose Maya animation scenes, clean stale references, and trigger logged playblasts without leaving the CLI.
- `onepiece dcc import-unreal --package <dir> --project <Project> --asset <Name>` &mdash; Rehydrate Maya-authored packages inside Unreal, with `--dry-run` support for previewing the generated import tasks.
- `onepiece aws sync-from` / `onepiece aws sync-to` &mdash; Entry points for synchronising media to and from AWS S3 buckets.
- `onepiece aws ingest` &mdash; Validates vendor/client deliveries, registers Versions in ShotGrid, and uploads media with detailed progress feedback.
- `onepiece validate reconcile ...` &mdash; Runs validation suites for ingest/publish workflows.
- `onepiece shotgrid package-playlist` &mdash; Bundles playlist media for client/vendor deliveries with MediaShuttle-ready folder structures.
- `onepiece shotgrid show-setup` &mdash; Seeds a project hierarchy from a CSV manifest while tracking progress shot-by-shot.
- `onepiece shotgrid deliver` &mdash; Builds MediaShuttle-ready ZIP archives from approved ShotGrid versions, writes manifests, and synchronises the package to S3.

Use `onepiece COMMAND --help` to inspect options for any command.

### Configuration essentials

Most commands rely on a handful of shared environment variables and optional
`onepiece.toml` profiles. The quickest way to confirm your setup is to run the
diagnostic helpers shown below:

```bash
# Display the resolved configuration profile and all merged sources
onepiece profile --show-sources

# Verify that the CLI can talk to AWS, ShotGrid, and the render adapters
onepiece info --check-integrations
```

Key environment variables recognised across the CLI surface:

| Variable | Purpose |
| --- | --- |
| `ONEPIECE_SHOTGRID_URL` | Base URL of the ShotGrid site the ingest helpers should target. |
| `ONEPIECE_SHOTGRID_SCRIPT` / `ONEPIECE_SHOTGRID_KEY` | API script credentials used for automation. |
| `AWS_PROFILE` | AWS profile applied when spawning `s5cmd` or other AWS-powered helpers. |
| `TRAFALGAR_DASHBOARD_TOKEN` | Bearer token required to query the dashboard and render APIs. |
| `ONEPIECE_PROJECT_ROOT` | Overrides the project root used when resolving `onepiece.toml` profiles. |
| `ONEPIECE_MAYA_PLUGINS` / `ONEPIECE_GPU` | Optional hints consumed by the DCC environment report when PyMEL or vendor detection is unavailable. |

Project and workspace defaults can be captured in `onepiece.toml` files. The
[configuration profile guide](docs/configuration_profiles.md) includes merging
rules, advanced examples, and a full key reference.

### Typical workflows

The CLI is designed to string together a handful of repeatable workflows. The
following snippets demonstrate the most common day-to-day sequences:

#### Validate and ingest a vendor delivery

```bash
# Dry-run first to inspect the generated report without uploading anything
onepiece aws ingest ./deliveries/EP101 --project "Show XYZ" --show-code XYZ \
  --source vendor --dry-run --report-format json --report-path reports/EP101.json

# Promote the report to a real ingest once the issues are resolved
onepiece aws ingest ./deliveries/EP101 --project "Show XYZ" --show-code XYZ \
  --source vendor --resume --checkpoint-dir ~/.cache/onepiece/ingest
```

#### Package and publish a DCC scene

```bash
onepiece dcc publish --dcc maya --scene-name ep101_seq010_sh010 --renders ./renders \
  --previews ./playblasts --otio editorial/ep101_seq010_sh010.otio \
  --metadata metadata/shot.json --destination dist/ep101_seq010_sh010 \
  --bucket s3://studio-prod-shots --show-code XYZ --dependency-summary
```

Scene names must now be simple package identifiers without directory separators, parent traversal, or absolute paths. The CLI normalises the supplied value before publishing and raises a validation error when the name would escape the package root. Maya exports that include Unreal metadata automatically trigger the new validation summary so scale, skeleton coverage, and naming issues are surfaced before uploads. 【F:src/apps/onepiece/dcc/publish.py†L58-L123】【F:src/libraries/dcc/maya/unreal_export_checker.py†L1-L120】

#### Submit a render job with profile defaults

```bash
# Profiles let you avoid retyping farm defaults each time
onepiece render submit --profile studio_farm --scene ./shots/shot.ma --frames 1001-1012 \
  --output ./renders/shot --user janed --priority 80
```

More step-by-step walkthroughs, including example manifests, are available in
[`docs/cli_walkthroughs.md`](docs/cli_walkthroughs.md).

#### Debug and playblast Maya animation scenes

```bash
# Report animation issues such as muted constraints or orphaned channels
onepiece dcc animation debug-animation --scene-name seq010_sh010_anim_v003

# Tidy up a heavy scene by pruning unused references and namespaces
onepiece dcc animation cleanup-scene --keep-unused-references --keep-namespaces

# Generate a playblast with logged metadata for downstream reviews
onepiece dcc animation playblast \
  --project SHOW01 --sequence sq010 --shot sh010 --artist robin.d \
  --camera renderCam --version 12 --output-directory ./playblasts/sh010_v012 \
  --metadata metadata/playblast.json --include-audio
```

The animation command group relies on pure-Python helpers and lazy Maya imports, so the CLI exits cleanly when PyMEL is unavailable instead of crashing mid-command. Detailed structured logging accompanies every run to feed dashboards and alerting. 【F:src/apps/onepiece/dcc/animation.py†L1-L194】【F:src/libraries/dcc/maya/__init__.py†L1-L48】

#### Import a published package into Unreal Engine

```bash
# Preview the Unreal tasks generated from a publish before running them in-editor
onepiece dcc import-unreal --package ./dist/seq010_sh010 --project OP --asset SK_Hero --dry-run
```

Packages that include `metadata.json` with Unreal import details now drive automatically constructed `AssetImportTask` objects. Failed Maya-to-Unreal validations abort the process with actionable error messages, while dry-run mode prints the planned tasks as JSON for review. 【F:src/apps/onepiece/dcc/unreal_import.py†L1-L83】【F:src/libraries/dcc/maya/unreal_importer.py†L58-L274】

### Operating the Perona dashboard

For day-to-day commands, configuration layering, and HTTP endpoint details see
[Perona dashboard operations](docs/perona_dashboard.md).

The `perona` CLI serves the VFX performance dashboard via uvicorn so teams can
inspect render and ingest metrics from a browser. Run
`perona web dashboard --host 0.0.0.0 --port 8065` to expose the FastAPI app;
toggle `--reload/--no-reload` for development auto-reloads and adjust
`--log-level` as needed, with defaults bound to `127.0.0.1:8065`. Supply
`--settings-path path/to/settings.toml` to load an alternate configuration
before the server boots; the CLI validates that the file exists and is readable
before continuing, and exports the path via `PERONA_SETTINGS_PATH` so the
FastAPI app picks it up on startup. Use `perona version` to print the
current dashboard build number directly from the CLI. 【F:src/apps/perona/app.py†L1-L174】

The runtime configuration loader emits warnings via the `apps.perona.engine`
logger whenever a candidate settings file cannot be read or parsed, including
the offending path and exception. Operators rolling out new releases should
watch for these messages in the Perona service logs to confirm that overrides
were accepted, otherwise the engine will fall back to the bundled defaults.

### Rendering standalone scenes with Chopper

The lightweight `chopper` CLI renders self-contained JSON scene descriptions. A
scene must declare positive, non-zero `width`, `height`, and `frames` fields in
addition to any objects. Scenes with zero or negative dimensions are rejected
before rendering so frame buffers are always valid.

Use the new `--format` flag to control how frames are exported:

- `--format ppm` (default) dumps each frame as a human-readable plain PPM file.
- `--format png` outputs lossless RGBA PNGs while preserving alpha.
- `--format gif` / `--format mp4` bundle the render into a single animation.

PNG and animation outputs rely on optional encoders. Install them when needed:

```bash
# Enable PNG helpers
pip install 'onepiece[chopper-images]'

# Enable GIF/MP4 helpers (requires an ffmpeg binary on PATH for MP4)
pip install 'onepiece[chopper-anim]'
```

When encoding animations you can tweak `--fps` to match the desired playback
speed. The writer stitches frames into GIFs directly via Pillow or shells out to
FFmpeg through `imageio-ffmpeg` for MP4 containers.

### Onboarding resources

If you are new to the toolkit, start with the dedicated onboarding material bundled in this repository:

- [Developer guide](docs/developer_guide.md) – workspace setup, repository structure, and the day-to-day development workflow.
- [CLI walkthroughs](docs/cli_walkthroughs.md) – step-by-step command sequences that rely on the sample manifests under `docs/examples/`.
- [Example assets](docs/examples/) – CSV manifests that you can plug into ingest, publish, and ShotGrid helpers while practising the CLI.

These resources provide a safe sandbox to explore the command surface before pointing the tooling at production data.

## What's new in the 1.0.0 release

### OnePiece CLI v1.0.0

- **Layered configuration profiles** – The CLI resolves settings from user, project, and workspace `onepiece.toml` files before honouring command-line overrides, and `onepiece profile` surfaces the merged result for troubleshooting.
- **Resumable ingest controls** – `onepiece aws ingest` exposes flags and profile keys for asyncio orchestration, worker pools, resumable uploads, and checkpoint tuning so large deliveries can be retried safely.
- **Capability-aware render submissions** – Render jobs automatically pick sensible priorities and chunk sizes from adapter metadata, with validation to reject values outside the advertised range before a request ever reaches the farm.

- **Maya animation workflows** – A dedicated Typer sub-app debugs animation scenes, performs configurable cleanup, and launches playblasts with structured logging so teams can automate checklist-driven reviews. 【F:src/apps/onepiece/dcc/animation.py†L1-L194】
- **Unreal package import pipeline** – Published Maya exports can be validated and rehydrated inside Unreal using the bundled importer and CLI command, complete with dry-run previews of generated tasks. 【F:src/apps/onepiece/dcc/unreal_import.py†L1-L83】【F:src/libraries/dcc/maya/unreal_importer.py†L58-L274】
- **Safer publishing defaults** – Scene names are strictly validated, dependency summaries now render correct paths, and Unreal export checks report skeleton, naming, and scale issues before uploads reach S3. 【F:src/apps/onepiece/dcc/publish.py†L58-L123】【F:src/libraries/dcc/maya/unreal_export_checker.py†L1-L120】
- **Resilient DCC detection** – Environment health checks treat plugin names case-insensitively, guard against missing PyMEL modules, and expose GPU/plugin overrides through environment variables to keep headless diagnostics reliable. 【F:src/libraries/validations/dcc.py†L1-L118】【F:src/libraries/dcc/maya/__init__.py†L1-L48】

### Trafalgar v1.0.0

- **Dashboard data resilience** – Project discovery now combines environment configuration with on-the-fly ShotGrid lookups and caches the results locally so teams can keep browsing known shows even if ShotGrid is offline.
- **Configurable ShotGrid caching** – Version queries honour TTL and record-count limits, dramatically reducing API pressure for frequently refreshed dashboards while falling back automatically when datasets grow beyond safe cache sizes.
- **Runtime cache controls** – Authenticated operators can inspect or tune the dashboard cache without restarting the service, including TTLs, record thresholds, project limits, and manual flushes for stale data.
- **Normalised status metrics** – Dashboard summaries collapse mixed-case and abbreviated ShotGrid statuses into canonical buckets, ensuring the overall status, per-project totals, and episode breakdowns tell the same story.
- **Delivery manifest optimisation** – Delivery payloads prefer upstream manifest data when provided, regenerate manifests only once per delivery, and gracefully handle packages that arrive without entry lists so operators still get a full audit trail.
- **Render job management** – The render FastAPI app now tracks submitted jobs in memory, exposes endpoints to list and inspect them, and supports adapter-powered cancellation, mirroring the CLI workflow for real-time follow-up.
- **Pluggable providers** – Delivery feeds and reconciliation sources register through a provider registry with built-in defaults, enabling studios to extend Trafalgar via Python entry points instead of hard-coding integrations. 【F:src/apps/trafalgar/providers/providers.py†L1-L210】

### Uta Control Center v1.0.0

- **Interactive CLI catalog** – Uta introspects every Typer command, renders them as cards grouped by command family, and lets operators append ad-hoc arguments before running them from the browser.
- **Embedded Trafalgar dashboard** – The Trafalgar FastAPI dashboard is mounted directly inside the UI so production metrics stay one click away from operational tooling.
- **Command execution sandbox** – Requests invoke the real CLI in a background thread, capture stdout/stderr, and stream the exit code back to the page so browser-triggered runs behave like terminal sessions.

## Render API error handling

The Trafalgar render service responds to failures with a consistent JSON envelope so operators and tooling can react deterministically. Error responses take the following form:

```json
{
  "error": {
    "code": "adapter.unavailable",
    "message": "Farm is temporarily offline.",
    "hint": "Check the farm status page and retry once the outage is resolved.",
    "context": {
      "farm": "mock"
    }
  }
}
```

- `code` – Machine-readable identifier that maps to a HTTP status (`adapter.unavailable` → `503 Service Unavailable`, `render.farm_not_found` → `404 Not Found`, etc.).
- `message` – Human-readable summary suitable for surfaced notifications.
- `hint` – Optional remediation guidance included when the service can recommend concrete next steps.
- `context` – Structured metadata (farm name, job identifier, and so on) to aid incident triage without digging through logs.

Adapters raise typed exceptions (for example `adapter.not_implemented`, `adapter.job_rejected`) which the FastAPI exception handler translates into this payload. Clients should rely on the `code` field rather than parsing free-form text.

## Trafalgar render history retention

The Trafalgar render service persists recent job submissions to a JSON file so operators can inspect them after restarts. Tune the retention knobs through environment variables before starting the API server:

- `TRAFALGAR_RENDER_JOBS_PATH` – location on disk where job history snapshots are stored.
- `TRAFALGAR_RENDER_JOBS_HISTORY_LIMIT` – maximum number of jobs kept in memory; older entries are dropped when the limit is exceeded.
- `TRAFALGAR_RENDER_JOBS_RETENTION_HOURS` – age-based retention window for persisted jobs. Entries older than the configured number of hours are pruned on save and when the service restarts.

The `/health` endpoint now reports the active history size, the number of jobs pruned due to retention limits, and the most recent compaction time so operators can confirm pruning activity without inspecting logs.

## Requirements

- Python 3.12 or newer
- Access to the required DCC tools on the machine running the CLI
- Credentials for any external integrations you plan to use (e.g. AWS profiles, ShotGrid API scripts)

## Installation

### From PyPI (recommended for workstations)

If you just need the CLI, install it directly from PyPI into an isolated environment:

```bash
python -m venv ~/.venvs/onepiece
source ~/.venvs/onepiece/bin/activate
pip install onepiece
```

### From source (for development or custom builds)

Clone the repository and install it in editable mode. The `dev` extras include linting and test tooling useful during development.

```bash
git clone https://github.com/<your-org>/onepiece.git
cd onepiece
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

To keep dependencies fresh, re-run `pip install -e .[dev]` after changing branches or updating `pyproject.toml`.

## Configuring integrations

Many commands rely on environment variables that map to your studio&rsquo;s infrastructure. Export them in your shell profile or pass them inline before running the CLI.

### ShotGrid

Set the variables required by the ShotGrid API client:

```bash
export ONEPIECE_SHOTGRID_URL="https://mystudio.shotgrid.autodesk.com"
export ONEPIECE_SHOTGRID_SCRIPT="pipeline-user"
export ONEPIECE_SHOTGRID_KEY="<script-key>"
```

You can verify the configuration with `onepiece info`.

#### Bulk ShotGrid helpers

The lightweight in-memory ShotGrid client that ships with the toolkit now
supports production-ready features for dealing with large deliveries:

- **Bulk operations** – create, update, or delete batches of entities with a
  single call.  The helpers automatically fan-out into the minimal number of API
  requests and share the same retry policy used by the rest of the client.
- **Resilient retries** – transient failures trigger exponential backoff with
  jitter and actionable log messages so that operators understand what happened
  and when the next attempt will fire.
- **Hierarchy templates** – declare entity trees (episodes, scenes, shots, …)
  once and apply them to new projects in a single command. Persist templates to
  JSON or YAML with `onepiece shotgrid templates save` and replay them later
  with `onepiece shotgrid templates apply` to bootstrap new shows quickly.
- **Playlist deliveries** – package playlists with `onepiece shotgrid package-playlist`
  to generate MediaShuttle-ready folders for client or vendor review sessions.

See ``libraries.shotgrid.client`` and ``libraries.shotgrid.playlist_delivery``
for usage examples and the accompanying unit tests for end-to-end
demonstrations of the new capabilities. The delivery command
(``onepiece shotgrid deliver``) complements these helpers by packaging approved
Versions, writing manifests, and synchronising the results to S3.

### AWS

The AWS commands leverage the standard AWS CLI configuration. Configure credentials via `aws configure`, or specify a profile when running commands. The optional `--profile` flag maps directly to the `AWS_PROFILE` environment variable so the spawned `s5cmd` process uses the matching credential profile:

```bash
onepiece aws sync-from --bucket my-bucket --show-code SHOW --folder plates --local-path /data/plates --profile studio-prod
```

`sync-from` mirrors the S5 `s5cmd sync` argument order: the S3 bucket/show-code
path is treated as the source and `local_path/folder` is the destination. This
ensures downloads populate the requested local directory without constructing an
S3-style path for the target. After each transfer, the CLI prints a summary of
uploaded, skipped, and failed files so operators can quickly audit the run.

## Working with the CLI

### Publishing DCC packages

The `onepiece dcc publish` command gathers renders, previews, and metadata produced by a DCC and uploads a packaged result to S3.

```bash
onepiece dcc publish \
  --dcc maya \
  --scene-name seq010_sh010_lighting_v002 \
  --renders /projects/show/renders/latest \
  --previews /projects/show/previews/latest.mov \
  --otio /projects/show/edit/shot.otio \
  --metadata /tmp/publish.json \
  --destination /tmp/output_package \
  --bucket studio-prod-data \
  --show-code SHOW \
  --show-type vfx
```

The command validates the target DCC, loads metadata from JSON, and reports the final package path once complete.

### Opening scenes from the CLI

Use `onepiece dcc open-shot` to launch a local scene file in the appropriate
DCC. Provide `--dcc` to force a specific application or omit it to let the
command infer the right tool from the file extension:

```bash
onepiece dcc open-shot --shot /projects/show/sequences/seq010/shot010/lighting_v002.nk
```

The CLI reports success once the DCC has been triggered and logs actionable
errors when it cannot locate or open the requested file.

### Delivering approved ShotGrid versions

Package client-ready deliveries straight from ShotGrid approvals using the
`deliver` subcommand:

```bash
onepiece shotgrid deliver \
  --project "Frost Giant" \
  --episodes EP01 EP02 \
  --context vendor_out \
  --output /tmp/frost_giant_vendor_out.zip \
  --manifest /tmp/frost_giant_vendor_out_manifest
```

The command validates each approved Version, adds the media to a ZIP archive,
writes JSON/CSV manifests, and uploads the results to the requested S3
context. When you supply `--manifest` the manifest files are also persisted to
disk for downstream automation.

### AWS synchronisation helpers

`onepiece aws sync-from` and `onepiece aws sync-to` wrap the data movers that mirror folders between local storage and S3. Both commands accept `--include/--exclude` globs and a `--dry-run` flag for auditing transfers.

### Media ingest workflow

The ingest command validates deliveries and registers the associated Versions in
ShotGrid before copying media to S3. Progress updates surface in the terminal so
operators can follow along as each file is processed:

```bash
onepiece aws ingest \
  /deliveries/vendor_drop_2024_02_14 \
  --project "Frost Giant" \
  --show-code FG \
  --source vendor \
  --vendor-bucket vendor_in \
  --client-bucket client_in
```

Manifests can be supplied to enrich ingest analytics and validate vendor drop
metadata without relying solely on filename parsing:

```bash
onepiece aws ingest \
  /deliveries/vendor_drop_2024_02_14 \
  --project "Frost Giant" \
  --show-code FG \
  --manifest delivery_manifest.json \
  --dry-run
```

The manifest may be authored as CSV or JSON. Both formats expect the following
fields for each entry:

| Field | Description |
| --- | --- |
| `show` | Show code that should match `--show-code`. |
| `episode` | Episode identifier, e.g. `ep001`. |
| `scene` | Scene identifier, e.g. `sc01`. |
| `shot` | Shot identifier, e.g. `0001`. |
| `asset` | Delivery asset/descriptor such as `comp`. |
| `version` | Integer version number. |
| `source_path` | Absolute path to the vendor's source media. |
| `delivery_path` | Expected filename (or relative path) in the ingest folder. |
| `checksum` | Optional checksum string used for audit trails. |

Example CSV row:

```csv
show,episode,scene,shot,asset,version,source_path,delivery_path,checksum
FG,ep010,sc02,0010,comp,4,/srv/vendor/shot.mov,FG_ep010_sc02_0010_comp_v004.mov,md5:deadbeef
```

Example JSON entry:

```json
{
  "files": [
    {
      "show": "FG",
      "episode": "ep010",
      "scene": "sc02",
      "shot": "0010",
      "asset": "comp",
      "version": 4,
      "source_path": "/srv/vendor/shot.mov",
      "delivery_path": "FG_ep010_sc02_0010_comp_v004.mov",
      "checksum": "md5:deadbeef"
    }
  ]
}
```

Invalid files are reported at the end of the run alongside a summary of skipped
and uploaded media.

### Inspecting your environment

`onepiece info` prints helpful debugging information such as Python version, active AWS profile, configured ShotGrid URL, and detected DCCs in the current `PATH`. This is a useful first command when onboarding a new workstation.

## Running the CLI from source

During development you can execute the application without installing it by running the module directly:

```bash
python -m src.apps.onepiece --help
```

This respects the same environment variables as the installed entry point and is convenient while iterating on code.

## Contributing

1. Fork and clone the repository.
2. Create a virtual environment and install dependencies with `pip install -e .[dev]`.
3. Run the quality suite before submitting changes:
   - `pytest`
   - `ruff check src tests`
   - `mypy`
4. Open a pull request with a description of your changes and any relevant screenshots or logs.

## Getting help

If you run into issues, open an issue in this repository with the command you ran and the resulting output. Include your OS, Python version, and whether you installed from PyPI or source to help us reproduce the problem quickly.
