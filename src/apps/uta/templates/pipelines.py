from __future__ import annotations


def render_pipeline_page(*, is_active: bool) -> str:
    active_class = "active" if is_active else ""
    return f"""
    <section id=\"page-pipelines\" class=\"page {active_class}\" data-pipeline-page>
      <div class=\"page-header\">\n        <h2>Pipeline orchestrator</h2>
        <p class=\"page-help\">Discover Trafalgar pipeline definitions, run orchestrated jobs, and inspect recent events.</p>
      </div>
      <div class=\"pipeline-toolbar\">
        <button type=\"button\" class=\"pipeline-refresh\" data-pipeline-refresh>Refresh pipelines</button>
        <span class=\"pipeline-status\" data-pipeline-status role=\"status\" aria-live=\"polite\"></span>
      </div>
      <p class=\"pipeline-empty\" data-pipeline-empty hidden>No pipelines are currently registered with the orchestrator.</p>
      <p class=\"pipeline-error\" data-pipeline-error hidden></p>
      <div class=\"pipeline-grid\" data-pipeline-cards></div>
      <template id=\"pipeline-card-template\">
        <article class=\"pipeline-card\" data-pipeline-card>
          <header class=\"pipeline-card-header\">
            <h3 data-pipeline-name></h3>
            <p class=\"pipeline-card-meta\">Pipeline ID: <code data-pipeline-identifier></code></p>
            <p class=\"pipeline-card-description\" data-pipeline-description></p>
          </header>
          <form class=\"pipeline-run-form\" data-pipeline-form autocomplete=\"off\">
            <div class=\"pipeline-parameters\" data-pipeline-parameters></div>
            <div class=\"pipeline-actions\">
              <button type=\"submit\" class=\"pipeline-run-button\" data-pipeline-run>
                <span class=\"pipeline-run-icon\" aria-hidden=\"true\">▶</span>
                <span>Run pipeline</span>
              </button>
              <button type=\"button\" class=\"pipeline-refresh-run\" data-pipeline-refresh-run hidden>Refresh status</button>
              <span class=\"pipeline-run-status\" data-pipeline-run-status aria-live=\"polite\"></span>
            </div>
          </form>
          <div class=\"pipeline-events\" data-pipeline-events hidden>
            <h4>Recent events</h4>
            <ol class=\"pipeline-event-list\" data-pipeline-event-list></ol>
          </div>
        </article>
      </template>
    </section>
    """


__all__ = ["render_pipeline_page"]
