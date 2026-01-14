# Pipeline ingest workflow

## Overview

The pipeline ingest workflow is a tag-driven, pipeline-first ingest that stores every incoming asset inside a canonical `.pipeline/ingest/<asset_id>/` directory. Each ingest preserves the original payload, writes a forward-compatible metadata record, creates tag-based links into working folders, and then runs any configured post-ingest hooks or Deadline actions.

The CLI entry point is:

```bash
onepiece ingest pipeline asset /path/to/source \
  --project-root /projects/show01 \
  --rules /projects/show01/config/ingest_link_rules.yaml \
  --tag plates \
  --controlled-tag vendor
```

## How ingest works

1. **Canonical storage** – The source file or directory is copied into `.pipeline/ingest/<asset_id>/` without modification.
2. **Metadata** – A `metadata.json` record is written alongside the payload.
3. **Tag-driven linking** – Link rules select the correct working folders and create symlinks (or copies when symlinks are unavailable).
4. **Post-ingest actions** – Hooks and optional Deadline jobs run after ingest completes.

## Metadata schema

Each ingest writes a `metadata.json` file with the following structure:

```json
{
  "schema_version": "1.0",
  "asset_id": "<unique-id>",
  "source_uri": "<original-path-or-uri>",
  "ingest_timestamp": "<UTC timestamp>",
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
    "controlled": ["vendor"]
  },
  "file_types": ["image"],
  "user": {
    "name": "<user>"
  },
  "machine": {
    "hostname": "<host>",
    "platform": "<os>"
  },
  "relationships": [
    {"type": "version_of", "target": "asset-123"}
  ]
}
```

The `schema_version` field keeps metadata forward-compatible as the schema evolves.

## Tag and linking rules

Link rules live in a YAML file. Each rule declares match conditions (tags, file types, extensions) and a destination path relative to the project root.

```yaml
schema_version: 1
rules:
  - name: plates
    target: assets/plates
    name_template: "{basename}"
    match:
      any_tags: [plates, plate]
      file_types: [image, video]
```

Supported match keys:

- `any_tags`: at least one tag must match.
- `all_tags`: all tags must match.
- `file_types`: matches any computed file type (for example `3d_model`, `image`, `video`).
- `extensions`: matches file extensions (for example `.exr`, `.usd`).

The `name_template` field accepts `{basename}`, `{asset_id}`, and `{source_uri}` placeholders.

## Hooks and Deadline actions

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

## Configuration files

Reference examples are provided in:

- `docs/examples/ingest_link_rules.yaml`
- `docs/examples/ingest_pipeline_config.yaml`
