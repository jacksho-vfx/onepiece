# CLI walkthroughs

These walkthroughs demonstrate common end-to-end flows using the OnePiece CLI. They rely on the sample assets in `docs/examples/` so that you can rehearse the workflows without connecting to production infrastructure.

> **Release spotlight (v1.0.0):** The CLI honours layered configuration profiles and resumable ingest toggles, Trafalgar introduces cache-tunable dashboards with job inspection endpoints, and the new Uta Control Center renders the command surface in your browser alongside the embedded dashboard.

### Adjusting dashboard cache behaviour

The dashboard cache limits can be tuned without restarting the service:

- Set the environment variables `ONEPIECE_DASHBOARD_CACHE_TTL`, `ONEPIECE_DASHBOARD_CACHE_MAX_RECORDS`, and `ONEPIECE_DASHBOARD_CACHE_MAX_PROJECTS` before launching the app to define the default TTL (in seconds), the maximum number of cached ShotGrid versions, and the maximum number of distinct projects that can be cached.
- At runtime, authenticate with the dashboard token and call the admin endpoints to inspect or update the cache:

  ```bash
  # Inspect the current cache configuration
  curl -H "Authorization: Bearer $TRAFALGAR_DASHBOARD_TOKEN" \
    http://localhost:8000/admin/cache

  # Reduce the TTL to 15 seconds, cap the cache to 2 projects, and flush existing entries
  curl -X POST -H "Authorization: Bearer $TRAFALGAR_DASHBOARD_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"ttl_seconds": 15, "max_projects": 2, "flush": true}' \
    http://localhost:8000/admin/cache
  ```

The update endpoint validates inputs and immediately applies the new limits to the in-memory cache used by ShotGrid queries, making it easy to evict stale data or throttle memory usage when operators notice the dataset growing.

## 1. Validate a workstation environment

1. Export temporary environment variables (replace the values with your sandbox credentials):

   ```bash
   export ONEPIECE_SHOTGRID_URL="https://example.shotgrid.autodesk.com"
   export ONEPIECE_SHOTGRID_SCRIPT="onboarding-bot"
   export ONEPIECE_SHOTGRID_KEY="not-a-real-key"
   export AWS_PROFILE="studio-dev"
   ```

2. Run the diagnostics command:

   ```bash
   onepiece info
   ```

   The command prints the interpreter version, discovered DCCs, and which integrations are active. Use the output to confirm that your workstation is ready before you attempt more invasive commands.

## 2. Dry-run an S3 ingest

The sample CSV `docs/examples/ingest_manifest.csv` describes footage that should be mirrored from S3 to local storage.

```csv
bucket_path,local_folder,expected_size_bytes,checksum
shows/demo/plates/seq010/sh010/main/v001/frame_####.exr,plates/seq010/sh010/main/v001,104857600,md5:0123456789abcdef0123456789abcdef
shows/demo/plates/seq020/sh030/main/v003/frame_####.exr,plates/seq020/sh030/main/v003,157286400,md5:fedcba9876543210fedcba9876543210
shows/demo/prerenders/seq010/sh010/concept/v002/*.jpg,concept/seq010/sh010/v002,5242880,md5:11223344556677881122334455667788
```

1. Stage a workspace for the ingest:

   ```bash
   export ONEPIECE_INGEST_ROOT="/tmp/onepiece_ingest"
   mkdir -p "$ONEPIECE_INGEST_ROOT"
   ```

2. Perform a dry run to inspect which files would transfer:

   ```bash
   onepiece aws sync-from \
     --bucket studio-demo-ingest \
     --show-code DEMO \
     --folder plates \
     --manifest docs/examples/ingest_manifest.csv \
     --local-path "$ONEPIECE_INGEST_ROOT" \
     --dry-run \
     --profile studio-dev
   ```

   Dry runs never create S3 objects or ShotGrid Versions; they emit analytics so you can verify the impact safely. Review the generated report before promoting the command to a full ingest.

   Passing `--profile` mirrors exporting `AWS_PROFILE` and ensures the underlying `s5cmd` call uses the same credential profile.

3. Once you are satisfied, remove the `--dry-run` flag to execute the transfer for real.

## 3. Analyse an ingest dry run

1. Create a scratch delivery directory with a couple of filenames that match and break the ingest rules:

   ```bash
   mkdir -p /tmp/onepiece_ingest_dry_run
   touch /tmp/onepiece_ingest_dry_run/SHOW01_ep001_sc01_0001_comp.mov
   touch /tmp/onepiece_ingest_dry_run/BADNAME.mov
   ```

2. Run the ingest command in dry-run mode while exporting analytics as JSON:

   ```bash
   onepiece aws ingest \
     /tmp/onepiece_ingest_dry_run \
     --project "Demo Project" \
     --show-code SHOW01 \
     --manifest docs/examples/delivery_manifest.json \
     --dry-run \
     --report-format json \
     --report-path /tmp/onepiece_ingest_report.json
   ```

   The CLI validates filenames, resolves destination buckets, and writes a JSON payload that lists the target `s3://` keys, rejected files, and any warnings encountered. The dry-run guarantee means no uploads or ShotGrid registrations occur—use the analytics report (JSON or CSV) to confirm everything looks correct before running the command for real.

   When using manifests, ensure each entry describes the show, episode, scene, shot,
   asset, version, source path, and expected delivery filename. The parser accepts
   the same columns whether the data is authored as CSV or under a `files`/`deliveries`
   key in JSON manifests.

3. Open the report to review the planned uploads before performing a real ingest:

   ```bash
   cat /tmp/onepiece_ingest_report.json
   ```

   The same `--report-format csv` flag streams a tabular version to stdout (or to `--report-path`) when you prefer spreadsheet tooling.

## 4. Package a DCC publish for QA

This scenario simulates a Maya lighting publish that bundles render outputs, previews, and metadata before pushing them to S3.

1. Review the metadata in `docs/examples/publish_metadata.csv` and tweak it to match your sandbox project.

```csv
key,value
scene,seq010_sh010_lighting_v002
shot,seq010_sh010
sequence,seq010
show,DEMO
frame_range,1001-1100
render_layer,beauty
version,2
artist,Robin Devops
notes,"QA dry run for onboarding"
```

2. Gather the input files referenced by the manifest and metadata. The example assumes the following layout:

   ```
   /projects/demo/seq010/sh010/
   ├── renders/lighting/v002/*.exr
   ├── previews/lighting/seq010_sh010_v002.mov
   └── metadata/publish.json
   ```

3. Run the publish command in report-only mode to confirm everything resolves:

   ```bash
   onepiece publish \
     --dcc maya \
     --scene-name seq010_sh010_lighting_v002 \
     --renders /projects/demo/seq010/sh010/renders/lighting/v002 \
     --previews /projects/demo/seq010/sh010/previews/lighting/seq010_sh010_v002.mov \
     --metadata docs/examples/publish_metadata.csv \
     --destination /tmp/onepiece_publish \
     --bucket studio-demo-publish \
     --show-code DEMO \
     --show-type vfx \
     --report-only
   ```

4. Inspect the generated report for any validation warnings. When the report looks good, rerun the command without `--report-only` to build and upload the package.

## 5. Bootstrap a ShotGrid project

The `docs/examples/shotgrid_hierarchy.csv` file models a minimal episodic show structure.

```csv
entity_type,name,parent_type,parent_name,code
Project,Demo Project,,,DEMO
Episode,ep01,Project,Demo Project,DEMO-EP01
Sequence,seq010,Episode,ep01,DEMO-EP01-SEQ010
Shot,sh010,Sequence,seq010,DEMO-EP01-SEQ010-SH010
Shot,sh020,Sequence,seq010,DEMO-EP01-SEQ010-SH020
Shot,sh030,Sequence,seq010,DEMO-EP01-SEQ010-SH030
Asset,chr_sparrow,Project,Demo Project,CHR-SPARROW
Task,lighting,Shot,sh010,lighting
Task,comp,Shot,sh010,comp
Task,animation,Shot,sh020,animation
Task,modeling,Asset,chr_sparrow,modeling
```

Run the helper to instantiate the hierarchy in your sandbox site:

```bash
onepiece shotgrid apply-hierarchy \
  --project "Demo Project" \
  --template docs/examples/shotgrid_hierarchy.csv \
  --dry-run
```

Dropping the `--dry-run` flag will create the entities using the resilient bulk helpers described in the README.

## 6. Package a ShotGrid playlist for delivery

The playlist packaging helpers can be exercised locally with the in-memory
ShotGrid client. Create a sandbox directory with placeholder media and then run
the script below to register versions, build a playlist, and generate a
MediaShuttle-ready package.

1. Create a temporary workspace with a couple of mock movie files:

   ```bash
   export ONEPIECE_PLAYLIST_ROOT="/tmp/onepiece_playlist_demo"
   mkdir -p "$ONEPIECE_PLAYLIST_ROOT"
   printf 'demo-1' > "$ONEPIECE_PLAYLIST_ROOT/seq010_sh010.mov"
   printf 'demo-2' > "$ONEPIECE_PLAYLIST_ROOT/seq010_sh020.mov"
   ```

2. Seed the in-memory ShotGrid client and package the playlist:

   ```bash
   python - <<'PY'
   from pathlib import Path

   from src.libraries.shotgrid.client import ShotgridClient
   from src.libraries.shotgrid.playlist_delivery import package_playlist_for_mediashuttle

   root = Path("$ONEPIECE_PLAYLIST_ROOT")
   client = ShotgridClient()

   version_one = client.register_version(
       project_name="Demo Project",
       shot_code="seq010_sh010",
       file_path=root / "seq010_sh010.mov",
       description="Client preview",
   )
   version_two = client.register_version(
       project_name="Demo Project",
       shot_code="seq010_sh020",
       file_path=root / "seq010_sh020.mov",
       description="Lighting update",
   )

   client.register_playlist(
       project_name="Demo Project",
       playlist_name="dailies",
       version_ids=[version_one["id"], version_two["id"]],
   )

   summary = package_playlist_for_mediashuttle(
       client,
       project_name="Demo Project",
       playlist_name="dailies",
       destination=root / "delivery",
       recipient="client",
   )

   print(f"Package created at: {summary.package_path}")
   print(f"Manifest entries: {len(summary.manifest['items'])}")
   PY
   ```

3. Inspect the generated directory and `manifest.json` file to confirm the
   playlist structure.

## 7. Exercise the DCC scaffolding stubs

The Trafalgar v1.0.0 release focuses on keeping the web suite responsive: the
dashboard auto-caches version lookups, gracefully handles sparse delivery
manifests, and the render API now mirrors the CLI's job lifecycle so you can
list, inspect, and cancel submissions via HTTP. Launch the services with the
Typer commands described above (`trafalgar web dashboard`, `trafalgar web
ingest`, `trafalgar web review`, and `trafalgar web render`) and use the snippet
below to export placeholder metadata with the existing DCC stubs while the web
services provide context for show-level analytics:

```bash
python - <<'PY'
from pathlib import Path

from libraries.dcc.client import BlenderClient
from libraries.dcc.enums import DCC

export_path = Path("/tmp/onepiece_dcc/metadata.json")
client = BlenderClient(dcc=DCC.BLENDER)
metadata = client.export_metadata(export_path)

print(f"Metadata written to: {export_path}")
print(metadata)
PY
```

The stub logs each action, writes a JSON template to the destination, and
returns a dictionary that mirrors the file content. Replace `BlenderClient` with
another client from `libraries.dcc.client` to rehearse the workflow for other
applications. When you are ready to wire up a real integration, override the
stub methods with application-specific logic and keep the CLI commands intact.

## 8. Orchestrate CLI runs from the Uta Control Center

1. Launch the browser UI alongside the Trafalgar dashboard:

   ```bash
   onepiece uta serve --host 127.0.0.1 --port 8050
   ```

   The command starts the FastAPI app, opens your default browser (unless you opt
   out with `--no-browser`), and mounts the Trafalgar dashboard under the same
   host for quick switching between metrics and operations.

2. Browse the command tabs or start typing in the global filter bar (press `/`
   to focus it from anywhere). Cards collapse in-place as you search, and the
   favourite toggle (click the ★ badge or hit `Shift+F`) sticks in
   `localStorage` so the commands you reach for most are one switch away on
   your next session.

3. Each card highlights parameter density and required flags with new badges so
   you can size up complex invocations at a glance. Add extra CLI flags in the
   *Additional arguments* field, then click **Run command** to invoke it without
   leaving the page—the run button now surfaces a spinner while the request is
   in flight.

4. Review the captured output and exit code that appears beneath the card. The
   status chip beside the button calls out success or failure with iconography
   and accessible contrast, making it easy to rehearse ingest, render, or
   validation flows in the same browser window that displays live production
   telemetry.

5. Switch to the **Dashboard** tab to explore live analytics. The credentials
   card persists either an API key/secret pair or bearer token in your browser
   so subsequent refreshes can call Trafalgar's protected
   `/render/jobs/metrics` endpoint. Once authenticated the interface renders
   Chart.js doughnut, line, and horizontal bar charts that mirror the fixture in
   [`docs/examples/trafalgar_render_metrics.json`](./examples/trafalgar_render_metrics.json),
   highlighting status distribution, submission throughput windows, and adapter
   utilisation trends.

---

Experimenting with these scenarios builds intuition for how the CLI behaves and gives you realistic command lines to adapt for production.
