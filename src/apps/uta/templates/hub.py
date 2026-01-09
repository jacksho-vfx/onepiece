from __future__ import annotations


def render_hub_page(*, is_active: bool) -> str:
    active_class = "active" if is_active else ""
    return f"""
    <section id=\"page-hub\" class=\"page {active_class}\" data-hub-page>
      <div class=\"page-header\">
        <h2>Pipeline + Render Hub</h2>
        <p class=\"page-help\">A guided flow for triggering pipelines, submitting render presets, and checking current status without memorising CLI flags.</p>
      </div>
      <p class=\"hub-status\" data-hub-status role=\"status\" aria-live=\"polite\"></p>
      <div class=\"hub-grid\">
        <article class=\"hub-card\">
          <header class=\"hub-card-header\">
            <h3>1. Run a pipeline</h3>
            <p>Pick a pipeline, fill in any required parameters, and trigger a run.</p>
          </header>
          <div class=\"hub-field\">
            <label for=\"hub-pipeline-select\">Pipeline</label>
            <div class=\"hub-select-row\">
              <select id=\"hub-pipeline-select\" data-hub-pipeline-select></select>
              <button type=\"button\" class=\"hub-button-secondary\" data-hub-pipeline-refresh>Refresh</button>
            </div>
            <p class=\"hub-muted\" data-hub-pipeline-description></p>
          </div>
          <form class=\"hub-form\" data-hub-pipeline-form autocomplete=\"off\">
            <div class=\"hub-parameters\" data-hub-pipeline-parameters></div>
            <button type=\"submit\" class=\"hub-button\" data-hub-pipeline-run>Run pipeline</button>
          </form>
          <p class=\"hub-result\" data-hub-pipeline-result></p>
        </article>
        <article class=\"hub-card\">
          <header class=\"hub-card-header\">
            <h3>2. Submit a render preset</h3>
            <p>Choose a preset with safe defaults and adjust only what changed for this shot.</p>
          </header>
          <div class=\"hub-field\">
            <label for=\"hub-render-select\">Render preset</label>
            <div class=\"hub-select-row\">
              <select id=\"hub-render-select\" data-hub-render-select></select>
              <button type=\"button\" class=\"hub-button-secondary\" data-hub-render-refresh>Refresh</button>
            </div>
            <p class=\"hub-muted\" data-hub-render-summary></p>
          </div>
          <form class=\"hub-form\" data-hub-render-form autocomplete=\"off\">
            <div class=\"hub-field\">
              <label for=\"hub-render-scene\">Scene (optional override)</label>
              <input id=\"hub-render-scene\" type=\"text\" data-hub-render-scene placeholder=\"Defaults to the preset scene\" />
            </div>
            <div class=\"hub-field\">
              <label for=\"hub-render-frames\">Frames (optional override)</label>
              <input id=\"hub-render-frames\" type=\"text\" data-hub-render-frames placeholder=\"Defaults to the preset frame range\" />
            </div>
            <div class=\"hub-field\">
              <label for=\"hub-render-output\">Output folder (optional override)</label>
              <input id=\"hub-render-output\" type=\"text\" data-hub-render-output placeholder=\"Defaults to the preset output folder\" />
            </div>
            <div class=\"hub-field\">
              <label for=\"hub-render-user\">Submitting user (optional)</label>
              <input id=\"hub-render-user\" type=\"text\" data-hub-render-user placeholder=\"Use the preset user or your login\" />
            </div>
            <button type=\"submit\" class=\"hub-button\" data-hub-render-submit>Submit render</button>
          </form>
          <p class=\"hub-result\" data-hub-render-result></p>
        </article>
        <article class=\"hub-card\">
          <header class=\"hub-card-header\">
            <h3>3. Check status</h3>
            <p>Paste a pipeline run ID or render job ID to see the latest state.</p>
          </header>
          <div class=\"hub-field\">
            <label for=\"hub-run-id\">Pipeline run ID</label>
            <div class=\"hub-select-row\">
              <input id=\"hub-run-id\" type=\"text\" data-hub-run-id placeholder=\"e.g. abc123\" />
              <button type=\"button\" class=\"hub-button-secondary\" data-hub-run-check>Check</button>
            </div>
            <p class=\"hub-result\" data-hub-run-status></p>
          </div>
          <div class=\"hub-field\">
            <label for=\"hub-job-id\">Render job ID</label>
            <div class=\"hub-select-row\">
              <input id=\"hub-job-id\" type=\"text\" data-hub-job-id placeholder=\"e.g. rjd-456\" />
              <button type=\"button\" class=\"hub-button-secondary\" data-hub-job-check>Check</button>
            </div>
            <p class=\"hub-result\" data-hub-job-status></p>
          </div>
        </article>
      </div>
    </section>
    """


__all__ = ["render_hub_page"]
