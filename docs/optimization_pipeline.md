# Optimization pipeline

## Overview

The optimization pipeline produces deterministic, non-destructive variants for
ingested assets. Variants are written under:

```
<project_root>/.pipeline/derived/<asset_id>/<variant>/
```

Each run emits an `opt_report.json` file containing the input hash, tool
versions, settings, size deltas, metrics, warnings, and errors. The ingest
metadata is updated with pointers to derived variants and a `preferred_variant`
field that resolves to the best available output (`usd`, `optimized`, `proxy`,
or `canonical`).

## CLI usage

```bash
onepiece optimize plan <asset_id>
onepiece optimize run <asset_id> --variant optimized
onepiece optimize submit <asset_id> --variant usd
onepiece optimize report <asset_id>
```

All commands support `--json` and `--dry-run` (where applicable).

## Configuration

Optimization settings live in `.pipeline/optimize_config.yaml`. A minimal
example:

```yaml
schema_version: 1
variants:
  optimized:
    enabled: true
    handlers:
      3d:
        clean_geometry: true
        merge_materials: true
        fix_normals: true
        strip_junk_nodes: true
        generate_lods: false
        decimate: false
        normalize_scene: true
        copy_textures: true
      texture:
        resize_max: null
        generate_mips: false
      cache:
        proxy: false
        validate_frames: true
  usd:
    enabled: true
    handlers:
      3d:
        convert_to_usd: true
        usd_format: usdc
        package_mode: flatten
        copy_textures: true
  proxy:
    enabled: true
    handlers:
      texture:
        resize_max: 1024
        format: png
        generate_mips: true
        mip_levels: 2
      cache:
        proxy: true
        validate_frames: true
deadline:
  pool: 3d
  group: pipeline
  priority: 50
```

Profile overrides are supported via `[profiles.<name>.optimize]` entries in
`onepiece.toml`.

## Handler coverage

### 3D models

Supported formats: FBX, OBJ, glTF/GLB, Alembic, USD, Blender (best-effort), Maya
ASCII/Binary (best-effort).

The handler performs best-effort geometry cleanups, optional LOD/decimation
steps (reported as skipped when tools are unavailable), scene normalization
metadata, texture reference discovery, and USD conversion when a converter is
available.

### Textures / images

The texture handler can resize, convert formats, generate mipmaps, and validate
alpha/bit depth expectations when Pillow is available. Unsupported operations
are marked as skipped in the report.

### Caches

Cache optimization validates frame ranges for numbered sequences and can emit
proxy variants (reported as skipped without external tools). Supported cache
formats include Alembic, VDB, BGEO, and USD.

## Rules-driven automation

Ingest rules can trigger optimizations:

```yaml
actions:
  optimize:
    - variant: usd
      mode: deadline
    - variant: proxy
      mode: local
```

This example submits USD conversion to Deadline and generates local proxy
textures on ingest.
