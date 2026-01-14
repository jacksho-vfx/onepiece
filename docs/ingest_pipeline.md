# Pipeline ingest workflow

## Overview

The pipeline ingest workflow is a tag-driven, pipeline-first ingest that stores every incoming asset inside a canonical `.pipeline/ingest/<asset_id>/` directory. Each ingest preserves the original payload, writes a forward-compatible metadata record, creates tag-based links into working folders, updates a local inventory index, and runs any configured post-ingest hooks or Deadline actions. Ingests are tracked in persistent sessions so you can queue multiple items, resume partial runs, and validate tags before executing.

The main entry points are:

```bash
onepiece ingest add /path/to/source /path/to/more \
  --project-root /projects/show01 \
  --rules /projects/show01/config/ingest_rules.yaml \
  --tag plates \
  --controlled-tag dept:plates

onepiece ingest run --session <session-id> --resume
```

## How ingest works

1. **Canonical storage** – The source file or directory is copied into `.pipeline/ingest/<asset_id>/` without modification.
2. **Metadata** – A `metadata.json` record is written alongside the payload and includes payload fingerprints.
3. **Tag-driven linking** – Rules select working folders and create symlinks (or copies when symlinks are unavailable).
4. **Post-ingest actions** – Hooks and optional Deadline jobs run after ingest completes.
5. **Inventory update** – The local index is updated for instant search.

## Metadata schema

Each ingest writes a `metadata.json` file with the following structure:

```json
{
  "schema_version": "1.2",
  "asset_id": "<unique-id>",
  "source_uri": "<original-path-or-uri>",
  "ingest_timestamp": "<UTC timestamp>",
  "payload_name": "<basename>",
  "payload_hash": "<sha256 of payload manifest>",
  "payload_size_bytes": 12345,
  "files": [
    {
      "path": "<relative path within payload>",
      "size_bytes": 12345,
      "sha256": "<sha256 hash>",
      "mime_type": "application/octet-stream",
      "file_type": "3d_model"
    }
  ],
  "tags": {
    "freeform": ["plates"],
    "controlled": ["dept:plates"]
  },
  "file_types": ["texture", "image"],
  "capabilities": {
    "texture": {
      "can_optimize": true,
      "can_validate": true,
      "can_convert": true
    }
  },
  "user": {
    "name": "<user>"
  },
  "machine": {
    "hostname": "<host>",
    "platform": "<os>"
  },
  "relationships": [
    {"type": "version_of", "target": "asset-123"}
  ],
  "derived_variants": [
    {
      "variant": "optimized",
      "path": "/projects/show/.pipeline/derived/<asset_id>/optimized",
      "report_path": "/projects/show/.pipeline/derived/<asset_id>/optimized/opt_report.json",
      "status": "success",
      "timestamp": "<UTC timestamp>"
    }
  ],
  "preferred_variant": "optimized"
}
```

The `schema_version` field keeps metadata forward-compatible as the schema evolves.

## Rules engine

Rules live in a YAML file and evaluate deterministically by `priority` (lower numbers first). Each rule declares match conditions and outputs. Outputs define one or more link targets. Actions optionally trigger hooks or Deadline jobs.

```yaml
schema_version: 1
rules:
  - name: plates
    priority: 10
    match:
      any_tags: [plates, dept:plates]
      file_types: [image, texture, video]
      path_contains: [\"/plates/\"]
    outputs:
      - target: assets/plates
        name_template: \"{basename}\"
    actions:
      hooks: [s5_aws_sync]
      optimize:
        - variant: proxy
          mode: local
  - name: assets
    priority: 20
    match:
      any_tags: [assets]
    outputs:
      - target: assets/library
        name_template: \"{basename}\"
    actions:
      deadline: [convert_to_usd]
      optimize:
        - variant: usd
          mode: deadline
```

Supported match keys:

- `any_tags`: at least one tag must match.
- `all_tags`: all tags must match.
- `file_types`: matches any computed file type (for example `3d_model`, `texture`, `image`, `video`).
- `extensions`: matches file extensions (for example `.exr`, `.usd`).
- `path_contains`: substring matches in the source path.
- `min_size_bytes` / `max_size_bytes`: match by payload size.

The `name_template` field accepts `{basename}`, `{asset_id}`, `{source_uri}`, and `{payload_name}` placeholders.

## Hooks, Deadline, and optimization actions

Hooks run after successful ingest and are tracked in `.pipeline/ingest/<asset_id>/hooks.json` so they are safe to re-run. Configure hooks in the ingest config file:

```yaml
schema_version: 1
hooks:
  - name: s5_aws_sync
    enabled: true
    config:
      destination: "s3://studio-ingest-backups/"
      aws_profile: "studio"
```

The bundled `s5_aws_sync` hook shells out to `aws s3 sync` and expects AWS credentials in the environment or an AWS profile.

Deadline actions are optional and configured via the same ingest config. When enabled, OnePiece writes Deadline job files and submits them through `deadlinecommand`:

```yaml
schema_version: 1
deadline:
  optimize_model:
    enabled: true
    pool: "3d"
    group: "pipeline"
    priority: 50
    plugin: "OptimizeModel"
  convert_to_usd:
    enabled: true
    pool: "3d"
    group: "pipeline"
    priority: 60
    plugin: "USDConversion"
```

Deadline jobs are only submitted for assets classified as `3d_model`.

Optimization actions allow rules to trigger local or Deadline optimization runs
for specific variants. Use `mode: local` to run immediately on the ingest host
or `mode: deadline` to submit the variant as a farm job.

## Configuration files

Reference examples are provided in:

- `docs/examples/ingest_rules.yaml`
- `docs/examples/ingest_pipeline_config.yaml`
- `docs/examples/ingest_tags.yaml`

## Sessions, queue, and resumability

Use `onepiece ingest add` to create a session and queue multiple items. Queue state is persisted in `.pipeline/queue/` so runs can resume after a crash. Each item writes progress markers (COPY, META, LINK, HOOKS, DEADLINE, OPTIMIZE, INDEX) to `.pipeline/ingest/<asset_id>/progress.json`.

```bash
onepiece ingest add /path/to/plates /path/to/assets --rules config/ingest_rules.yaml
onepiece ingest run --session <session-id> --resume
onepiece ingest status --session <session-id>
```

Use `--force` to rebuild derived metadata or re-run hooks.

## Tag inference and validation

Tags are inferred from file types, extensions, and path heuristics (for example `/plates/` or `/assets/char/`). Optional user tags are appended. To enforce a controlled vocabulary, define `.pipeline/tags.yaml` in your project and validate:

```bash
onepiece ingest validate --session <session-id>
```

## Dry-run planning

Preview how rules resolve without copying data:

```bash
onepiece ingest plan /path/to/source --rules config/ingest_rules.yaml --tag plates
```

## Inventory search

The inventory index lives in `.pipeline/index/` and is updated automatically during ingest runs. Search by tag or name:

```bash
onepiece inventory search --tag dept:plates
onepiece inventory search --name plate
onepiece inventory show <asset-id>
```
