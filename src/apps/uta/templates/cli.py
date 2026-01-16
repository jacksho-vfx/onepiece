from __future__ import annotations

import json
from html import escape
from typing import TypedDict

from apps.uta.web_cli import CommandSpec, PageSpec

from .app_flags import render_app_flag


def slugify(name: str) -> str:
    return "-".join(name.lower().split())


class PresetOption(TypedDict):
    label: str
    values: list[str]


def render_parameters(command: CommandSpec, *, command_id: str) -> str:
    if not command.parameters:
        return '<p class="parameters-empty">No configurable parameters.</p>'

    def normalise_examples(raw: object) -> list[str]:
        if not raw or not isinstance(raw, (list, tuple, set)):
            return []
        examples: list[str] = []
        for item in raw:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                examples.append(text)
        return examples

    def normalise_presets(raw: object) -> list[PresetOption]:
        if not raw or not isinstance(raw, (list, tuple, set)):
            return []
        presets: list[PresetOption] = []
        for item in raw:
            if isinstance(item, dict):
                label = str(
                    item.get("label")
                    or item.get("name")
                    or item.get("title")
                    or item.get("id")
                    or ""
                ).strip()
                raw_values = item.get("values", item.get("value"))
                values: list[str] = []
                if isinstance(raw_values, str):
                    values = [
                        line.strip() for line in raw_values.splitlines() if line.strip()
                    ]
                elif isinstance(raw_values, (list, tuple, set)):
                    values = [
                        str(value).strip() for value in raw_values if str(value).strip()
                    ]
                if label and values:
                    presets.append({"label": label, "values": values})
            else:
                text = str(item).strip()
                if text:
                    presets.append({"label": text, "values": [text]})
        return presets

    fields: list[str] = []
    for index, parameter in enumerate(command.parameters):
        field_id = f"{command_id}-param-{index}"
        label_html = escape(parameter.label)
        help_html = (
            f'<p class="param-help">{escape(parameter.help_text)}</p>'
            if parameter.help_text
            else ""
        )
        meta_bits: list[str] = []
        if parameter.required and not parameter.is_flag:
            meta_bits.append("required")
        if parameter.default is not None:
            meta_bits.append(f"default: {escape(parameter.default)}")
        if parameter.allows_multiple:
            meta_bits.append("multiple values allowed")
        meta_html = (
            f"<span class=\"param-meta\">({' | '.join(escape(bit) for bit in meta_bits)})</span>"
            if meta_bits
            else ""
        )

        cli_names_json = escape(json.dumps(parameter.cli_names), quote=True)
        common_attrs = (
            f' data-cli-names="{cli_names_json}"'
            f' data-parameter-kind="{escape(parameter.kind, quote=True)}"'
            f' data-accepts-value="{"true" if parameter.accepts_value else "false"}"'
            f' data-is-flag="{"true" if parameter.is_flag else "false"}"'
            f' data-allow-multiple="{"true" if parameter.allows_multiple else "false"}"'
        )

        if parameter.is_flag:
            checked = " checked" if parameter.default_bool else ""
            checkbox_attrs = common_attrs
            if parameter.default_bool is not None:
                checkbox_attrs += f' data-default-state="{"true" if parameter.default_bool else "false"}"'
            control_html = (
                f'<input id="{field_id}" name="{escape(parameter.name)}"'
                f' type="checkbox" class="command-parameter"{checkbox_attrs}{checked} />'
            )
            field_html = (
                '<div class="parameter-field parameter-flag">'
                f'  <label for="{field_id}" class="parameter-flag-label">'
                f"    {control_html}"
                f'    <span class="parameter-flag-text">'
                f'      <span class="param-label">{label_html}</span>'
                f"      {meta_html}"
                f"    </span>"
                f"  </label>"
                f"  {help_html}"
                "</div>"
            )
        else:
            required_attr = " required" if parameter.required else ""
            placeholder = "Required value" if parameter.required else "Optional value"
            helper_html = ""
            examples = normalise_examples(getattr(parameter, "examples", None))
            presets = normalise_presets(getattr(parameter, "presets", None))
            if parameter.allows_multiple:
                control_html = (
                    f'<textarea id="{field_id}" name="{escape(parameter.name)}"'
                    f' class="command-parameter command-parameter-multivalue" rows="3"'
                    f'{common_attrs}{required_attr} placeholder="{escape(placeholder)}"'
                    ' autocomplete="off" spellcheck="false"></textarea>'
                )
                helper_bits: list[str] = []
                if examples:
                    chips = "".join(
                        f'<button type="button" class="parameter-helper-chip"'
                        f' data-target="{field_id}" data-example="{escape(example, quote=True)}">'
                        f"{escape(example)}"
                        "</button>"
                        for example in examples
                    )
                    helper_bits.append(
                        '<div class="param-helper param-helper-examples">'
                        '  <span class="param-helper-label">Examples</span>'
                        f'  <div class="param-helper-chips">{chips}</div>'
                        "</div>"
                    )
                if presets:
                    options = "".join(
                        f'<option value="{escape(preset["label"], quote=True)}"'
                        f' data-values="{escape(json.dumps(preset["values"]), quote=True)}">'
                        f"{escape(preset['label'])}"
                        "</option>"
                        for preset in presets
                    )
                    helper_bits.append(
                        '<label class="param-helper param-helper-presets">'
                        '  <span class="param-helper-label">Presets</span>'
                        f'  <select class="parameter-preset" data-target="{field_id}">'
                        '    <option value="">Select a preset</option>'
                        f"    {options}"
                        "  </select>"
                        "</label>"
                    )
                if helper_bits:
                    helper_html = (
                        '<div class="param-helper-set">'
                        + "".join(helper_bits)
                        + "</div>"
                    )
            else:
                control_html = (
                    f'<input id="{field_id}" name="{escape(parameter.name)}"'
                    f' type="text" class="command-parameter"{common_attrs}{required_attr}'
                    f' placeholder="{escape(placeholder)}" autocomplete="off" />'
                )
            field_html = (
                '<div class="parameter-field">'
                f'  <label for="{field_id}" class="parameter-label">'
                f'    <span class="param-label">{label_html}</span>'
                f"    {meta_html}"
                f"  </label>"
                f"  {control_html}"
                f"  {helper_html}"
                f"  {help_html}"
                "</div>"
            )
        fields.append(field_html)

    return '<div class="parameter-fields">' + "".join(fields) + "</div>"


def render_command(command: CommandSpec) -> str:
    command_id = "-".join(command.path)
    parameters_html = render_parameters(command, command_id=command_id)
    summary = escape(command.summary or "")
    command_base_segments = ["onepiece", *command.path]
    invocation_display = escape(" ".join(command_base_segments))
    command_base_json = escape(json.dumps(command_base_segments), quote=True)
    output_id = f"output-{'-'.join(command.path)}"
    parameter_count = len(command.parameters)
    required_count = sum(1 for parameter in command.parameters if parameter.required)
    if parameter_count == 0:
        density_label = "No parameters"
        density_key = "none"
    elif parameter_count <= 2:
        density_label = "Light inputs"
        density_key = "light"
    elif parameter_count <= 5:
        density_label = "Moderate inputs"
        density_key = "moderate"
    else:
        density_label = "Dense inputs"
        density_key = "dense"
    metadata_parts: list[str] = []
    metadata_parts.append(
        '<span class="badge badge-density badge-density-'
        + density_key
        + f'""><span aria-hidden="true">⚙️</span>{escape(density_label)}</span>'
    )
    metadata_parts.append(
        '<span class="badge badge-parameters"><span aria-hidden="true">🧾</span>'
        + escape(str(parameter_count))
        + (" params" if parameter_count != 1 else " param")
        + "</span>"
    )
    if required_count:
        metadata_parts.append(
            '<span class="badge badge-required"><span aria-hidden="true">❗</span>'
            + escape(str(required_count))
            + (" required" if required_count != 1 else " required")
            + "</span>"
        )
    metadata_html = "".join(metadata_parts)
    keyword_bits: list[str] = [
        command.display_name,
        command.summary or "",
        " ".join(command.path),
    ]
    for parameter in command.parameters:
        keyword_bits.append(parameter.label)
        keyword_bits.append(parameter.help_text)
    keyword_payload = escape(" ".join(keyword_bits).lower(), quote=True)
    command_path = " ".join(escape(segment) for segment in command.path)
    return f"""
    <article class=\"command-card\" tabindex=\"0\" data-command-id=\"{escape(command_id)}\" data-command-path=\"{command_path}\"
 data-keywords=\"{keyword_payload}\" data-parameter-count=\"{parameter_count}\" data-required-count=\"{required_count}\">
      <header class=\"command-header\">
        <div class=\"command-title-row\">
          <h3>{escape(command.display_name)}</h3>
          <button type=\"button\" class=\"favourite-toggle\" aria-pressed=\"false\" aria-label=\"Toggle favourite for {escape(command.display_name)}\" aria-keyshortcuts=\"Shift+F\">
            <span class=\"favourite-icon\" aria-hidden=\"true\">☆</span>
            <span class=\"favourite-text\">Favourite</span>
          </button>
        </div>
        <code class=\"command-invocation\" data-command-base=\"{command_base_json}\" aria-live=\"polite\">{invocation_display}</code>
        <div class=\"command-meta\">{metadata_html}</div>
      </header>
      <p class=\"command-summary\">{summary}</p>
      <form class=\"command-form\">
        {parameters_html}
        <div class=\"form-actions\">
          <button type=\"submit\" class=\"run-command\" aria-keyshortcuts=\"Enter\">
            <span class=\"button-icon\" aria-hidden=\"true\">▶</span>
            <span class=\"button-label\">Run command</span>
          </button>
          <button type=\"button\" class=\"copy-command\" aria-keyshortcuts=\"Shift+C\" title=\"Copy the full CLI invocation\">
            <span class=\"button-icon\" aria-hidden=\"true\">📋</span>
            <span class=\"button-label\">Copy command</span>
          </button>
          <div class=\"status-cluster\">
            <span class=\"progress-indicator\" aria-hidden=\"true\" hidden></span>
            <span class=\"status\" aria-live=\"polite\"></span>
            <button type=\"button\" class=\"copy-executed-command\" disabled>
              <span class=\"button-icon\" aria-hidden=\"true\">📑</span>
              <span class=\"button-label\">Copy executed</span>
            </button>
            <button type=\"button\" class=\"download-output\" disabled>
              <span class=\"button-icon\" aria-hidden=\"true\">⬇️</span>
              <span class=\"button-label\">Download output</span>
            </button>
          </div>
        </div>
      </form>
      <pre id=\"{output_id}\" class=\"command-output\" hidden></pre>
    </article>
    """


def render_page(page: PageSpec, *, is_active: bool) -> str:
    commands_html = "".join(render_command(command) for command in page.commands)
    if not commands_html:
        commands_html = (
            '<p class="empty-page">No commands are available for this section.</p>'
        )
    help_text = escape(page.help_text or "")
    page_id = f"page-{slugify(page.name)}"
    active_class = "active" if is_active else ""
    flag_html = render_app_flag(page.name, size="md")
    return f"""
    <section id=\"{page_id}\" class=\"page {active_class}\">
      <div class=\"page-header\">
        <div class=\"page-header-text\">
          {flag_html}
          <div class=\"page-header-copy\">
            <h2>{escape(page.name.title())}</h2>
            <p class=\"page-help\">{help_text}</p>
          </div>
        </div>
        <div class=\"page-actions\" aria-label=\"Page filters\">
          <button type=\"button\" class=\"filter-pill favourites-pill\" data-favourites-pill aria-pressed=\"false\" aria-label=\"Show favourite commands only\">
            <span class=\"pill-icon\" aria-hidden=\"true\">★</span>
            <span class=\"pill-label\">Favourites</span>
          </button>
          <span class=\"visually-hidden\" data-filter-status aria-live=\"polite\"></span>
        </div>
      </div>
      {commands_html}
    </section>
    """


def normalise_root_path(root_path: str | None) -> str:
    if not root_path or root_path == "/":
        return ""
    return root_path.rstrip("/")


def with_root_path(root_path: str, path: str) -> str:
    if not path.startswith("/"):
        return path
    if not root_path:
        return path
    return f"{root_path}{path}"


__all__ = [
    "slugify",
    "render_parameters",
    "render_command",
    "render_page",
    "normalise_root_path",
    "with_root_path",
]
