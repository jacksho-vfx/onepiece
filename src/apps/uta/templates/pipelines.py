from __future__ import annotations

from .app_flags import render_app_flag


def render_pipeline_page(*, is_active: bool) -> str:
    active_class = "active" if is_active else ""
    flag_html = render_app_flag("Pipelines", size="md")
    return f"""
    <section id=\"page-pipelines\" class=\"page {active_class}\" data-pipeline-page>
      <div class=\"page-header\">
        <div class=\"page-header-text\">
          {flag_html}
          <div class=\"page-header-copy\">
            <h2>Pipeline orchestrator</h2>
            <p class=\"page-help\">Discover Trafalgar pipeline definitions, run orchestrated jobs, and inspect recent events.</p>
          </div>
        </div>
      </div>
      <div class=\"pipeline-toolbar\">
        <button type=\"button\" class=\"pipeline-refresh\" data-pipeline-refresh>Refresh pipelines</button>
        <span class=\"pipeline-status\" data-pipeline-status role=\"status\" aria-live=\"polite\"></span>
      </div>
      <div class=\"pipeline-filters\">
        <label class=\"pipeline-search\" aria-label=\"Search pipelines\">
          <span class=\"pipeline-search-icon\" aria-hidden=\"true\">🔎</span>
          <input type=\"search\" class=\"pipeline-search-input\" placeholder=\"Search by name or ID\" data-pipeline-search />
        </label>
        <div class=\"pipeline-status-filters\" data-pipeline-status-chips role=\"group\" aria-label=\"Filter pipelines by status\">
          <button type=\"button\" class=\"pipeline-status-chip is-active\" data-pipeline-status-chip data-status=\"all\">All statuses</button>
        </div>
      </div>
      <p class=\"pipeline-empty\" data-pipeline-empty hidden>No pipelines are currently registered with the orchestrator.</p>
      <p class=\"pipeline-error\" data-pipeline-error hidden></p>
      <div class=\"pipeline-grid\" data-pipeline-cards></div>
      <template id=\"pipeline-card-template\">
        <article class=\"pipeline-card\" data-pipeline-card data-pipeline-name-value data-pipeline-identifier-value data-pipeline-status-value>
          <header class=\"pipeline-card-header\">
            <h3 data-pipeline-name></h3>
            <p class=\"pipeline-card-meta\">Pipeline ID: <code data-pipeline-identifier></code></p>
            <p class=\"pipeline-card-status\" data-pipeline-status-text></p>
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
