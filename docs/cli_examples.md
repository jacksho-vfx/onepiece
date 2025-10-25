# CLI Examples 

## OnePiece CLI (`onepiece …` / `python -m apps.onepiece …`)

The root Typer app wires the `info`, `aws`, `dcc`, `review`, `render`, `notify`, `shotgrid`, and `validate` command groups under the `onepiece` console script. When developing inside the repository you can invoke the same tree with `python -m apps.onepiece` after exporting `PYTHONPATH=src`. 【F:src/apps/onepiece/app.py†L3-L24】

> **Release spotlight (v1.0.0):** Configuration profiles can now be layered across user, project, and workspace scopes, ingest commands expose resumable upload controls, render submissions validate adapter capabilities up-front, and the brand-new Uta Control Center mirrors every CLI command in a browser alongside the Trafalgar dashboard.
>
> **Latest merges:** A new `dcc animation` command group debugs Maya scenes, cleans namespaces, and automates playblasts with structured logging. Published packages can be re-imported into Unreal through `dcc import-unreal`, and the publish workflow now enforces safe scene names while surfacing Unreal export validation summaries. Environment health checks treat plugin names case-insensitively and fall back gracefully when PyMEL is unavailable, and Trafalgar's reconcile helpers sit atop a pluggable provider registry with sensible defaults. 【F:src/apps/onepiece/dcc/animation.py†L1-L220】【F:src/apps/onepiece/dcc/unreal_import.py†L1-L78】【F:src/apps/onepiece/dcc/publish.py†L39-L119】【F:src/libraries/platform/validations/dcc.py†L1-L194】【F:src/apps/trafalgar/providers/providers.py†L1-L210】

### Core
- `python -m apps.onepiece info` — print environment and configuration details for the pipeline client. Append `--format json` to emit a machine-readable report for automation or dashboards.

### AWS utilities
- `python -m apps.onepiece aws ingest <delivery_folder> --project <shotgrid_project> --show-code <show_code> [--source vendor|client --vendor-bucket <bucket> --client-bucket <bucket> --dry-run --report-format <json|csv> --report-path <file>]` — validate deliveries, upload to S3, and register ShotGrid Versions. The analytics flags capture dry-run results as JSON or CSV so you can review invalid files and planned uploads before executing a real ingest.
- **Ingest concurrency and resume tuning** – Heavy deliveries can be parallelised and resumed via additional flags and environment variables:
  - `--max-workers` / `INGEST_MAX_WORKERS` – Size of the thread pool used for uploads (defaults to 4 when unset).
  - `--use-asyncio/--no-use-asyncio` / `INGEST_USE_ASYNCIO` – Toggle asyncio task orchestration instead of threads.
  - `--resume/--no-resume` / `INGEST_RESUME_ENABLED` – Enable resumable uploads with checkpoint persistence.
  - `--checkpoint-dir` / `INGEST_CHECKPOINT_DIR` – Directory containing persisted multipart checkpoints (defaults to `.ingest-checkpoints`).
  - `--checkpoint-threshold` / `INGEST_CHECKPOINT_THRESHOLD` – Minimum file size (bytes) before checkpoints are recorded; default is 512 MiB.
  - `--upload-chunk-size` / `INGEST_UPLOAD_CHUNK_SIZE` – Chunk size (bytes) used for resumable transfers; default is 64 MiB.
- `python -m apps.onepiece aws sync-from <bucket> <show_code> <folder> <local_path> [--dry-run --include <pattern> … --exclude <pattern> … --profile <aws_profile>]` — mirror S3 data into a local directory via `s5cmd` with progress reporting. Supplying `--profile` sets `AWS_PROFILE` for the spawned `s5cmd` command.
- `python -m apps.onepiece aws sync-to <bucket> <show_code> <folder> <local_path> [--dry-run --include <pattern> … --exclude <pattern> … --profile <aws_profile>]` — push local renders back to S3 using `s5cmd` with progress feedback. The optional profile maps to `AWS_PROFILE` for the sync process.

### Troubleshooting ShotGrid ingest failures

If the ingest command exits early, review the CLI heading and take the suggested action before retrying:

- **Configuration error** – ShotGrid rejected the configured credentials. Refresh the API script key or token, update the environment variables used by ingest, and rerun the command once authentication succeeds.
- **Validation error** – ShotGrid rejected the version payload. Confirm that the referenced project, shot, and naming conventions exist in ShotGrid, adjust the filenames or ShotGrid schema, then retry the ingest.
- **External service error** – The CLI could not reach ShotGrid. Check VPN or proxy connectivity, verify the ShotGrid status page, and rerun the ingest after connectivity is restored.
- **Empty delivery folder** – The ingest command will exit early with a validation warning pointing to the dry-run report. Run the same command with `--dry-run`, share the generated report with the vendor to request the missing files, then rerun ingest once the delivery is complete.

### DCC integration
- `python -m apps.onepiece dcc open-shot --shot <scene_file> [--dcc <maya|nuke|…>]` — open the scene in the inferred or specified DCC, surfacing external errors cleanly.
- `python -m apps.onepiece dcc publish --dcc <dcc> --scene-name <name> --renders <path> --previews <path> --otio <file> --metadata <file> --destination <dir> --bucket <bucket> --show-code <code> [--show-type vfx|prod --profile <aws_profile> --direct-upload-path s3://… --dependency-summary]` — package and publish a scene, optionally summarising dependency validation.
- `python -m apps.onepiece dcc animation debug-animation [--scene-name current] [--fail-on-warnings]` — analyse animation metadata and report muted constraints, channel mismatches, and frame range issues before shots leave Maya.
- `python -m apps.onepiece dcc animation cleanup-scene [--remove-unused-references/--keep-unused-references …]` — prune unused references, empty namespaces, and unknown nodes with per-operation toggles.
- `python -m apps.onepiece dcc animation playblast --project <code> --shot <shot> --artist <user> --camera <name> --version <n> --output-directory <dir> [--sequence <seq> --format mov|avi|… --metadata <file> --include-audio]` — generate logged playblasts that downstream review tools can ingest.
- `python -m apps.onepiece dcc import-unreal --package <dir> --project <project> --asset <asset> [--dry-run]` — rebuild an Unreal asset from a published package, previewing the generated `AssetImportTask` payloads with `--dry-run`.

### Review & render
- `python -m apps.onepiece review dailies --project <project> [--playlist <playlist>] --output <quicktime.mov> [--codec <codec>]` — assemble ShotGrid Versions into a review QuickTime and manifest using the helpers in `libraries.automation.review`. 【F:src/libraries/automation/review/dailies.py†L1-L320】
- `python -m apps.onepiece render submit --dcc <dcc> --scene <scene_file> [--frames <range>] --output <frames_dir> [--farm <deadline|tractor|…> --priority <n> --chunk-size <n> --user <user>]` — submit a render job to the configured farm adapter with detailed logging and adapter-aware defaults. 【F:src/apps/onepiece/render/submit.py†L1-L308】
- `python -m apps.onepiece render preset save <name> --farm <deadline|tractor|…> [--dcc <dcc>] [--scene <scene>] [--frames <range>] [--output <path>] [--priority <n> --chunk-size <n> --user <user>]` — persist a reusable render submission preset to disk. 【F:src/apps/onepiece/render/submit.py†L309-L388】

### Notifications and status tracking
- `python -m apps.onepiece notify email --subject "Daily ingest status" --message "Ingest completed successfully" [--recipients user@example.com,user2@example.com --mock]` — send a simple email summary once ingest completes. Provide a comma-separated recipient list or run with `--mock` to log instead of sending. 【F:src/apps/onepiece/notify/email.py†L1-L61】
- `python -m apps.onepiece notify slack --subject "Render batch" --message "Renders completed" [--mock]` — post status updates to Slack through the configured notifier backend. 【F:src/apps/onepiece/notify/slack.py†L1-L47】

### Validation helpers
- `python -m apps.onepiece validate reconcile ingest --delivery ./deliveries/EP101 --report reports/EP101.json` — compare a delivery folder against the last ingest report and surface deltas before re-running ingest.
- `python -m apps.onepiece validate otio --file editorial/shot.otio --strict` — confirm that editorial timelines match the schema expected by the publish command.
- `python -m apps.onepiece validate farm-capabilities --farm mock --preset highprio` — render the adapter capability matrix for the given farm/preset combination so supervisors can review chunking and priority limits.

### Configuration inspection
- `python -m apps.onepiece profile` — print the active profile name and resolved values.
- `python -m apps.onepiece profile --show-sources` — list each configuration layer (user, project, workspace, CLI) that contributed to the merged profile, including file paths.
- `python -m apps.onepiece profile export --profile studio --output profiles/studio.json` — convert a TOML profile into JSON so it can be consumed by external automation tooling.

## Example reports

Many commands can emit machine-readable reports. These snippets show the shape
of the generated files to help you integrate them with downstream systems.

### Ingest dry-run JSON

```json
{
  "delivery": "./deliveries/EP101",
  "project": "Show XYZ",
  "show_code": "XYZ",
  "status": "dry-run",
  "files": [
    {
      "path": "plates/shot010/v001/shot010_v001.mov",
      "action": "upload",
      "size_bytes": 104857600,
      "warnings": []
    }
  ]
}
```

### Render submission summary

```json
{
  "scene": "shots/ep101_seq010_sh010.ma",
  "farm": "mock",
  "frames": "1001-1012",
  "priority": 75,
  "chunk_size": 4,
  "user": "janed",
  "submitted_at": "2024-05-08T12:30:00+00:00"
}
```

Feed these reports into your monitoring or communication pipelines to keep the
team updated without scraping terminal output.
- `python -m apps.onepiece render preset list` — enumerate discovered render presets with key metadata.
- `python -m apps.onepiece render preset use <name> [--scene <scene>] [--frames <range>] [--output <path>] [--farm <deadline|tractor|…> --dcc <dcc> --priority <n> --chunk-size <n> --user <user>]` — apply a preset and submit a job with optional overrides.

### Notifications
- `python -m apps.onepiece notify email --subject <text> --message <body> [--recipients user@example.com,… --mock]` — send or mock an email notification through the configured backend.
- `python -m apps.onepiece notify slack --subject <text> --message <body> [--mock]` — post (or mock) a Slack notification via the notifier registry.

### ShotGrid operations
- `python -m apps.onepiece shotgrid deliver --project <project> --context <vendor_out|client_out> --output <delivery.zip> [--episodes <ep> … --manifest <path>]` — bundle approved Versions, upload to S3, and emit manifests.
- `python -m apps.onepiece shotgrid show-setup <shots.csv> <project> [--template <template_name>]` — create ShotGrid shots from a CSV with progress feedback.
- `python -m apps.onepiece shotgrid package-playlist --project <project> --playlist <playlist> [--destination <path> --recipient client|vendor]` — build a MediaShuttle delivery for a playlist.
- `python -m apps.onepiece shotgrid bulk-playlists <create|update|delete> [--input <payload.json> --id <playlist_id> …]` — run bulk playlist CRUD with JSON payloads or ID lists.
- `python -m apps.onepiece shotgrid bulk-versions <create|update|delete> [--input <payload.json> --id <version_id> …]` — perform bulk Version operations similarly.
- `python -m apps.onepiece shotgrid save-template --input <template.(json|yaml)> --output <normalized.(json|yaml)>` — validate and persist hierarchy templates.
- `python -m apps.onepiece shotgrid load-template --input <template.(json|yaml)> --project <project> [--context <context.(json|yaml)>]` — apply a saved hierarchy template to a project.
- `python -m apps.onepiece shotgrid upload-version --project <project> --shot <shot_code> --file <media>` — create a new ShotGrid Version and upload media.
- `python -m apps.onepiece shotgrid version-zero <shots.csv> --project-name <project> [--fps <fps>]` — generate “version zero” proxies for each shot and upload them.

### Validation helpers
- `python -m apps.onepiece validate names <show> <episode> <scene> <shot> [<asset>]` — confirm naming conventions across entities, failing on any invalid entry.
- `python -m apps.onepiece validate names-batch [--csv <names.csv> | --dir <directory>]` — batch-validate names from CSV or filesystem sources with rich output.
- `python -m apps.onepiece validate paths <path> [<path> …]` — preflight filesystem paths for existence, writability, and free space.
- `python -m apps.onepiece validate asset-consistency <manifest.json> [--local-base <root>] [--project <project> --context <vendor_in|…>] [--scope shots|assets]` — compare manifest expectations against local storage and S3 parity checks.
- `python -m apps.onepiece validate dcc-environment [--dcc <maya> --dcc <nuke> …]` — render DCC environment health reports, normalising plugin names and falling back to environment hints when PyMEL is unavailable.
- `python -m apps.onepiece validate reconcile --project <project> [--scope shots|assets|versions --context <vendor_in|…> --csv <report.csv> --json <report.json>]` — reconcile ShotGrid, filesystem, and optional S3 inventories with progress reporting. The underlying job now consumes data from the default provider registry entry, making it easy to swap in custom data sources via entry points when required. 【F:src/libraries/platform/validations/dcc.py†L1-L194】【F:src/apps/trafalgar/providers/providers.py†L1-L210】

## Trafalgar CLI (`python -m apps.trafalgar …`)

The Trafalgar Typer app exposes dashboard and ingest helpers under `web` and `ingest` groups.

- `python -m apps.trafalgar web dashboard [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>] [--demo-port <port>] [--open-browser/--no-open-browser] [--browser-path <alias>]` — serve the dashboard ASGI app via uvicorn, optionally mirror it with studio-style demo data on a secondary port, and launch the default (or specified) browser once the service boots.
- `python -m apps.trafalgar web ingest [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — launch the ingest API through the web command group.
- `python -m apps.trafalgar web render [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — expose the render submission API with job listing, inspection, and cancellation endpoints mirroring the CLI payloads.
- `python -m apps.trafalgar web review [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — start the review API for playlist previews and approvals.
- `python -m apps.trafalgar ingest [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — start the ingest API directly via the ingest sub-app callback.

## Uta Control Center (`onepiece uta …`)

- `python -m apps.uta serve [--host <host>] [--port <port>] [--reload/--no-reload] [--open-browser/--no-browser]` — launch the browser UI that introspects every OnePiece CLI command, groups them into tabs, and embeds the Trafalgar dashboard within the same session. The interface now ships with a persistent search/favourites bar, density badges for parameter-heavy commands, and clearer status chips for long-running jobs.
- `python -m apps.uta serve --no-browser` — start the server without opening a browser automatically (useful on headless hosts or when tunnelling the port).
- `curl -X POST http://127.0.0.1:8050/api/run -H 'Content-Type: application/json' -d '{"path": ["aws", "ingest"], "extra_args": "--help"}'` — invoke a command through the JSON API to integrate the UI runner with automation.

