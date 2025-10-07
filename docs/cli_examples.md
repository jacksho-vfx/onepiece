# CLI Examples

## OnePiece CLI (`python -m apps.onepiece …`)

The root Typer app wires the `info`, `aws`, `dcc`, `review`, `render`, `notify`, `shotgrid`, and `validate` command groups (including the reconciliation helper) under `python -m apps.onepiece`.

### Core
- `python -m apps.onepiece info` — print environment and configuration details for the pipeline client.

### AWS utilities
- `python -m apps.onepiece aws ingest <delivery_folder> --project <shotgrid_project> --show-code <show_code> [--source vendor|client --vendor-bucket <bucket> --client-bucket <bucket> --dry-run --report-format <json|csv> --report-path <file>]` — validate deliveries, upload to S3, and register ShotGrid Versions. The analytics flags capture dry-run results as JSON or CSV so you can review invalid files and planned uploads before executing a real ingest.
- **Ingest concurrency and resume tuning** – Heavy deliveries can be parallelised and resumed via additional flags and environment variables:
  - `--max-workers` / `INGEST_MAX_WORKERS` – Size of the thread pool used for uploads (defaults to 4 when unset).
  - `--use-asyncio/--no-use-asyncio` / `INGEST_USE_ASYNCIO` – Toggle asyncio task orchestration instead of threads.
  - `--resume/--no-resume` / `INGEST_RESUME_ENABLED` – Enable resumable uploads with checkpoint persistence.
  - `--checkpoint-dir` / `INGEST_CHECKPOINT_DIR` – Directory containing persisted multipart checkpoints (defaults to `.ingest-checkpoints`).
  - `--checkpoint-threshold` / `INGEST_CHECKPOINT_THRESHOLD` – Minimum file size (bytes) before checkpoints are recorded; default is 512 MiB.
  - `--upload-chunk-size` / `INGEST_UPLOAD_CHUNK_SIZE` – Chunk size (bytes) used for resumable transfers; default is 64 MiB.
- `python -m apps.onepiece aws sync-from <bucket> <show_code> <folder> <local_path> [--dry-run --include <pattern> … --exclude <pattern> …]` — mirror S3 data into a local directory via `s5cmd` with progress reporting.
- `python -m apps.onepiece aws sync-to <bucket> <show_code> <folder> <local_path> [--dry-run --include <pattern> … --exclude <pattern> …]` — push local renders back to S3 using `s5cmd` with progress feedback.

### Troubleshooting ShotGrid ingest failures

If the ingest command exits early, review the CLI heading and take the suggested action before retrying:

- **Configuration error** – ShotGrid rejected the configured credentials. Refresh the API script key or token, update the environment variables used by ingest, and rerun the command once authentication succeeds.
- **Validation error** – ShotGrid rejected the version payload. Confirm that the referenced project, shot, and naming conventions exist in ShotGrid, adjust the filenames or ShotGrid schema, then retry the ingest.
- **External service error** – The CLI could not reach ShotGrid. Check VPN or proxy connectivity, verify the ShotGrid status page, and rerun the ingest after connectivity is restored.
- **Empty delivery folder** – The ingest command will exit early with a validation warning pointing to the dry-run report. Run the same command with `--dry-run`, share the generated report with the vendor to request the missing files, then rerun ingest once the delivery is complete.

### DCC integration
- `python -m apps.onepiece dcc open-shot --shot <scene_file> [--dcc <maya|nuke|…>]` — open the scene in the inferred or specified DCC, surfacing external errors cleanly.
- `python -m apps.onepiece dcc publish --dcc <dcc> --scene-name <name> --renders <path> --previews <path> --otio <file> --metadata <file> --destination <dir> --bucket <bucket> --show-code <code> [--show-type vfx|prod --profile <aws_profile> --direct-upload-path s3://… --dependency-summary]` — package and publish a scene, optionally summarising dependency validation.

### Review & render
- `python -m apps.onepiece review dailies --project <project> [--playlist <playlist>] --output <quicktime.mov> [--burnin/--no-burnin --codec <codec>]` — assemble ShotGrid Versions into a review QuickTime and manifest.
- `python -m apps.onepiece render submit --dcc <dcc> --scene <scene_file> [--frames <range>] --output <frames_dir> [--farm <deadline|tractor|…> --priority <n> --chunk-size <n> --user <user>]` — submit a render job to the configured farm adapter with detailed logging and adapter-aware defaults.
- `python -m apps.onepiece render preset save <name> --farm <deadline|tractor|…> [--dcc <dcc>] [--scene <scene>] [--frames <range>] [--output <path>] [--priority <n> --chunk-size <n> --user <user>]` — persist a reusable render submission preset to disk.
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
- `python -m apps.onepiece validate dcc-environment [--dcc <maya> --dcc <nuke> …]` — render DCC environment health reports, erroring if any requirement is unmet.
- `python -m apps.onepiece validate reconcile --project <project> [--scope shots|assets|versions --context <vendor_in|…> --csv <report.csv> --json <report.json>]` — reconcile ShotGrid, filesystem, and optional S3 inventories with progress reporting.

## Trafalgar CLI (`python -m apps.trafalgar …`)

The Trafalgar Typer app exposes dashboard and ingest helpers under `web` and `ingest` groups.

- `python -m apps.trafalgar web dashboard [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — serve the dashboard ASGI app via uvicorn.
- `python -m apps.trafalgar web ingest [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — launch the ingest API through the web command group.
- `python -m apps.trafalgar web render [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — expose the render submission API with job listing, inspection, and cancellation endpoints mirroring the CLI payloads.
- `python -m apps.trafalgar web review [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — start the review API for playlist previews and approvals.
- `python -m apps.trafalgar ingest [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — start the ingest API directly via the ingest sub-app callback.

