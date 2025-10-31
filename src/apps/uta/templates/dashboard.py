from __future__ import annotations

from .cli import with_root_path


def render_dashboard_page(*, is_active: bool, root_path: str) -> str:
    active_class = "active" if is_active else ""
    dashboard_root = with_root_path(root_path, "/dashboard/")
    return f"""
    <section id=\"page-dashboard\" class=\"page {active_class}\" data-dashboard-root=\"{dashboard_root}\">
      <div class=\"page-header\">
        <h2>Trafalgar Dashboard</h2>
        <p class=\"page-help\">Live Trafalgar analytics rendered alongside the OnePiece command surface.</p>
      </div>
      <article class=\"dashboard-auth-card\" data-dashboard-auth>
        <div class=\"dashboard-auth-header\">
          <h3>Dashboard credentials</h3>
          <p>Provide Trafalgar API credentials so the charts below can fetch protected analytics.</p>
        </div>
        <form class=\"dashboard-auth-form\" autocomplete=\"off\">
          <div class=\"dashboard-auth-grid\">
            <label class=\"dashboard-field\" for=\"dashboard-api-key\">
              <span>API key</span>
              <input id=\"dashboard-api-key\" name=\"dashboard-api-key\" type=\"text\" inputmode=\"text\" placeholder=\"X-API-Key\" data-dashboard-api-key />
            </label>
            <label class=\"dashboard-field\" for=\"dashboard-api-secret\">
              <span>API secret</span>
              <input id=\"dashboard-api-secret\" name=\"dashboard-api-secret\" type=\"password\" placeholder=\"X-API-Secret\" data-dashboard-api-secret />
            </label>
            <label class=\"dashboard-field\" for=\"dashboard-bearer-token\">
              <span>Bearer token</span>
              <input id=\"dashboard-bearer-token\" name=\"dashboard-bearer-token\" type=\"password\" placeholder=\"Authorization token\" data-dashboard-bearer />
            </label>
          </div>
          <div class=\"dashboard-auth-actions\">
            <button type=\"button\" class=\"dashboard-auth-clear\" data-dashboard-auth-clear>Clear credentials</button>
            <p class=\"dashboard-auth-note\">Stored securely in local storage; nothing is sent until a chart request is made.</p>
          </div>
        </form>
      </article>
      <div class=\"dashboard-charts\" data-dashboard-charts>
        <article class=\"chart-card\" data-chart-id=\"render-status\" data-empty-message=\"No render job history yet.\" data-error-message=\"Unable to load render analytics.\">
          <div>
            <h3>Render jobs by status</h3>
            <p>Snapshot of render submissions across all farms.</p>
          </div>
          <canvas id=\"dashboard-chart-render-status\" class=\"chart-canvas\" role=\"img\" aria-label=\"Render jobs by status\" height=\"220\" hidden></canvas>
          <p class=\"chart-placeholder\">No render job history yet.</p>
        </article>
        <article class=\"chart-card\" data-chart-id=\"render-throughput\" data-empty-message=\"No recent submissions.\" data-error-message=\"Unable to load throughput analytics.\">
          <div>
            <h3>Submission throughput</h3>
            <p>Rolling submission windows highlighting busy render periods.</p>
          </div>
          <canvas id=\"dashboard-chart-render-throughput\" class=\"chart-canvas\" role=\"img\" aria-label=\"Render submission throughput\" height=\"220\" hidden></canvas>
          <p class=\"chart-placeholder\">No recent submissions.</p>
        </article>
        <article class=\"chart-card\" data-chart-id=\"render-adapters\" data-empty-message=\"No adapter utilisation recorded.\" data-error-message=\"Unable to load adapter analytics.\">
          <div>
            <h3>Adapter utilisation</h3>
            <p>Compare job totals across configured render adapters.</p>
          </div>
          <canvas id=\"dashboard-chart-render-adapters\" class=\"chart-canvas\" role=\"img\" aria-label=\"Render adapter utilisation\" height=\"220\" hidden></canvas>
          <p class=\"chart-placeholder\">No adapter utilisation recorded.</p>
        </article>
      </div>
      <p class=\"dashboard-link\"><a href=\"{dashboard_root}\" target=\"_blank\" rel=\"noreferrer noopener\">Open the full Trafalgar dashboard</a></p>
    </section>
    """


__all__ = ["render_dashboard_page"]
