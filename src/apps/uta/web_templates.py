from __future__ import annotations

from html import escape
import json
from typing import Mapping

from .templates import (
    normalise_root_path as _normalise_root_path_impl,
    render_command as _render_command_impl,
    render_dashboard_page as _render_dashboard_page_impl,
    render_page as _render_cli_page_impl,
    render_parameters as _render_parameters_impl,
    render_pipeline_page as _render_pipeline_page_impl,
    slugify as _slugify_impl,
    with_root_path as _with_root_path_impl,
)
from .web_cli import CLI_PAGES

_render_parameters = _render_parameters_impl
_render_command = _render_command_impl
_render_page = _render_cli_page_impl
_render_pipeline_page = _render_pipeline_page_impl
_render_dashboard_page = _render_dashboard_page_impl
_normalise_root_path = _normalise_root_path_impl
_with_root_path = _with_root_path_impl
_slugify = _slugify_impl


def _render_index(
    root_path: str,
    *,
    active_slug: str | None = None,
    default_credentials: Mapping[str, str] | None = None,
) -> str:
    nav_items: list[str] = []
    content_sections: list[str] = []

    page_order = list(CLI_PAGES.items())
    default_slug: str | None = None
    slug_lookup: dict[str, str] = {}
    for name, _ in page_order:
        slug = _slugify(name)
        slug_lookup[slug] = name
        if default_slug is None:
            default_slug = slug

    selected_slug = active_slug
    pipeline_slug = "pipelines"
    pipeline_active = False
    dashboard_active = False
    cli_active_slug: str | None = None

    if not page_order:
        cli_active_slug = None
        if selected_slug == pipeline_slug:
            pipeline_active = True
        else:
            dashboard_active = selected_slug in (None, "dashboard")
            if not dashboard_active and selected_slug != pipeline_slug:
                dashboard_active = True
    else:
        if selected_slug == "dashboard":
            dashboard_active = True
        elif selected_slug == pipeline_slug:
            pipeline_active = True
        elif selected_slug and selected_slug in slug_lookup:
            cli_active_slug = selected_slug
        else:
            cli_active_slug = default_slug

        if pipeline_active or dashboard_active:
            cli_active_slug = None
        elif cli_active_slug is None:
            cli_active_slug = default_slug

    for index, (name, page) in enumerate(page_order):
        page_id = f"page-{_slugify(name)}"
        slug = _slugify(name)
        if cli_active_slug is None:
            is_active = not (pipeline_active or dashboard_active) and index == 0
        else:
            is_active = slug == cli_active_slug
        active_class = "active" if is_active else ""
        default_flag = "true" if index == 0 else "false"
        nav_items.append(
            f'<button type="button" class="tab-button {active_class}" data-target="{page_id}" data-tab="{slug}" data-default-tab="{default_flag}">{escape(name.title())}</button>'
        )
        content_sections.append(_render_page(page, is_active=is_active))
    pipeline_class = "active" if pipeline_active else ""
    nav_items.append(
        f'<button type="button" class="tab-button {pipeline_class}" data-target="page-pipelines" data-tab="{pipeline_slug}" data-default-tab="false">Pipelines</button>'
    )
    content_sections.append(_render_pipeline_page(is_active=pipeline_active))
    dashboard_class = "active" if dashboard_active else ""
    nav_items.append(
        f'<button type="button" class="tab-button {dashboard_class}" data-target="page-dashboard" data-tab="dashboard" data-default-tab="false">Dashboard</button>'
    )
    content_sections.append(
        _render_dashboard_page(is_active=dashboard_active, root_path=root_path)
    )

    navigation = "".join(nav_items)
    pages_html = "".join(content_sections)
    css_href = _with_root_path(root_path, "/static/control_center.css")
    js_src = _with_root_path(root_path, "/static/control_center.js")
    credentials_attr = ""
    if default_credentials:
        cleaned: dict[str, str] = {}
        for key, value in default_credentials.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            trimmed = value.strip()
            if not trimmed:
                continue
            cleaned[key] = trimmed
        if cleaned:
            credentials_json = json.dumps(cleaned, sort_keys=True)
            credentials_attr = (
                f' data-dashboard-default-credentials="{escape(credentials_json)}"'
            )

    return f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>Uta Control Center</title>
        <link rel=\"stylesheet\" href=\"{css_href}\" />
        <script src=\"https://cdn.jsdelivr.net/npm/chart.js@4.4.6/dist/chart.umd.min.js\" id=\"uta-dashboard-chartjs\" crossorigin=\"anonymous\" referrerpolicy=\"no-referrer\"></script>
      </head>
      <body data-root-path=\"{escape(root_path)}\" data-default-tab=\"{escape(default_slug or '')}\"{credentials_attr}>
        <header class=\"app-header\">
          <h1>Uta Control Center</h1>
          <p>Trigger OnePiece CLI operations through a streamlined interface and explore the Trafalgar dashboard without leaving your browser.</p>
        </header>
        <section class=\"utility-bar\" aria-label=\"Command filters\">
          <label class=\"search-field\" for=\"command-search\">
            <span class=\"search-icon\" aria-hidden=\"true\">🔍</span>
            <input id=\"command-search\" name=\"command-search\" type=\"search\" autocomplete=\"off\" placeholder=\"Filter commands (press /)\" />
          </label>
          <label class=\"favourite-filter\" for=\"favourites-toggle\">
            <input id=\"favourites-toggle\" type=\"checkbox\" />
            <span class=\"favourite-filter-label\"><span aria-hidden=\"true\">★</span>Favourites only</span>
          </label>
        </section>
        <nav class=\"tab-bar\" role=\"tablist\">
          {navigation}
        </nav>
        <main>
          {pages_html}
        </main>
        <script src=\"{js_src}\" defer></script>
      </body>
    </html>
    """


__all__ = [
    "_slugify",
    "_render_parameters",
    "_render_command",
    "_render_page",
    "_normalise_root_path",
    "_with_root_path",
    "_render_pipeline_page",
    "_render_dashboard_page",
    "_render_index",
]
