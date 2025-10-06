# CLI Examples

## OnePiece CLI (`python -m apps.onepiece …`)

The root Typer app wires the `info`, `aws`, `dcc`, `review`, `render`, `notify`, `shotgrid`, and `validate` command groups (including the reconciliation helper) under `python -m apps.onepiece`.

### Core
- `python -m apps.onepiece info` — print environment and configuration details for the pipeline client.

### AWS utilities
- `python -m apps.onepiece aws ingest <delivery_folder> --project <shotgrid_project> --show-code <show_code> [--source vendor|client --vendor-bucket <bucket> --client-bucket <bucket> --dry-run]` — validate deliveries, upload to S3, and register ShotGrid Versions.
- `python -m apps.onepiece aws sync-from <bucket> <show_code> <folder> <local_path> [--dry-run --include <pattern> … --exclude <pattern> …]` — mirror S3 data into a local directory via `s5cmd` with progress reporting.
- `python -m apps.onepiece aws sync-to <bucket> <show_code> <folder> <local_path> [--dry-run --include <pattern> … --exclude <pattern> …]` — push local renders back to S3 using `s5cmd` with progress feedback.

### DCC integration
- `python -m apps.onepiece dcc open-shot --shot <scene_file> [--dcc <maya|nuke|…>]` — open the scene in the inferred or specified DCC, surfacing external errors cleanly.
- `python -m apps.onepiece dcc publish --dcc <dcc> --scene-name <name> --renders <path> --previews <path> --otio <file> --metadata <file> --destination <dir> --bucket <bucket> --show-code <code> [--show-type vfx|prod --profile <aws_profile> --direct-upload-path s3://… --dependency-summary]` — package and publish a scene, optionally summarising dependency validation.

### Review & render
- `python -m apps.onepiece review dailies --project <project> [--playlist <playlist>] --output <quicktime.mov> [--burnin/--no-burnin --codec <codec>]` — assemble ShotGrid Versions into a review QuickTime and manifest.
- `python -m apps.onepiece render submit --dcc <dcc> --scene <scene_file> [--frames <range>] --output <frames_dir> [--farm <deadline|tractor|…> --priority <n> --user <user>]` — submit a render job to the configured farm adapter with detailed logging.

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
- `python -m apps.trafalgar web render [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — expose the render submission API mirroring the CLI payloads.
- `python -m apps.trafalgar web review [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — start the review API for playlist previews and approvals.
- `python -m apps.trafalgar ingest [--host <host>] [--port <port>] [--reload/--no-reload] [--log-level <level>]` — start the ingest API directly via the ingest sub-app callback.

