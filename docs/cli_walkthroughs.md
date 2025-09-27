# CLI walkthroughs

These walkthroughs demonstrate common end-to-end flows using the OnePiece CLI. They rely on the sample assets in `docs/examples/` so that you can rehearse the workflows without connecting to production infrastructure.

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
     --dry-run
   ```

3. Once you are satisfied, remove the `--dry-run` flag to execute the transfer for real.

## 3. Package a DCC publish for QA

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

## 4. Bootstrap a ShotGrid project

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

---

Experimenting with these scenarios builds intuition for how the CLI behaves and gives you realistic command lines to adapt for production.
