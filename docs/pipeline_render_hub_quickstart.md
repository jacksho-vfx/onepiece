# Pipeline + render hub quickstart

> **At a glance:** Use the new hub to run a pipeline, submit a render preset, and check status from a single guided flow—either in the CLI or the Uta Control Center.

## CLI: one command, guided prompts

1. Launch the hub:

   ```bash
   onepiece hub
   ```

2. Choose **`pipeline-render`** to run a pipeline first, then submit a render preset.
3. Follow the prompts to:
   - Select a pipeline and fill in any required parameters.
   - Optionally watch pipeline events until completion.
   - Pick a render preset and adjust only the scene, frame range, or output folder if needed.

The hub reuses the pipeline parameter schema and render preset validation, so defaults are always shown before you type anything.

## Uta Control Center: one-click navigation

1. Launch Uta (for example via the tester demo or `python -m apps.uta`).
2. Open the **Pipeline + Render** tab.
3. Work through the three cards:
   - **Run a pipeline** – choose a pipeline, supply parameters, and trigger a run.
   - **Submit a render preset** – choose a preset and apply optional overrides.
   - **Check status** – paste a pipeline run ID or render job ID to see the latest state.

## Common one-click paths

- **Kick off today’s ingest pipeline and submit the matching render preset**
  - CLI: `onepiece hub` → `pipeline-render`.
  - Uta: Pipeline + Render → Run a pipeline → Submit a render preset.

- **Verify progress on a pipeline run from a dailies meeting**
  - CLI: `onepiece hub` → `pipeline-status`.
  - Uta: Pipeline + Render → Check status.

- **Submit a known render preset without touching CLI flags**
  - CLI: `onepiece hub` → `render-preset`.
  - Uta: Pipeline + Render → Submit a render preset.
