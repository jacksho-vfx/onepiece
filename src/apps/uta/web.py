"""FastAPI application exposing a browser GUI for OnePiece commands."""

from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass, field
from enum import Enum
from html import escape
from typing import Sequence, Any

from inspect import _empty as INSPECT_EMPTY

import click
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typer.main import get_command
from typer.testing import CliRunner

from apps.onepiece.app import app as cli_app
from apps.trafalgar.web.dashboard import app as dashboard_app


@dataclass
class ParameterSpec:
    """Metadata describing a single CLI parameter."""

    label: str
    help_text: str
    required: bool
    default: str | None


@dataclass
class CommandSpec:
    """Metadata describing a CLI command that can be invoked from the GUI."""

    path: list[str]
    summary: str
    parameters: list[ParameterSpec] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return " ".join(self.path)

    @property
    def invocation(self) -> str:
        return "onepiece " + " ".join(self.path)


@dataclass
class PageSpec:
    """Collection of commands grouped by the first CLI segment."""

    name: str
    help_text: str
    commands: list[CommandSpec] = field(default_factory=list)


AUTO_PARAM_NAMES = {"help", "install_completion", "show_completion"}


def _normalise_help(value: str | None) -> str:
    return (value or "").strip()


def _format_parameter_label(parameter: click.Parameter) -> Any:
    if isinstance(parameter, click.Option):
        names = list(parameter.opts) + list(parameter.secondary_opts)
        label = ", ".join(names) if names else parameter.name
    else:
        label = parameter.human_readable_name
    if parameter.type:
        label = f"{label} ({parameter.type.name})"
    return label


def _is_missing_default(parameter: click.Parameter, value: Any) -> bool:
    if value is None:
        return True
    if value is Ellipsis:
        return True
    parameter_empty = getattr(click.Parameter, "empty", None)
    if parameter_empty is not None and value is parameter_empty:
        return True
    if INSPECT_EMPTY is not None and value is INSPECT_EMPTY:
        return True
    if getattr(parameter, "required", False):
        if isinstance(value, Enum):
            return True
        value_type = type(value)
        module = getattr(value_type, "__module__", "")
        name = value_type.__name__
        if module.startswith("typer.") and (
            "Placeholder" in name or name.startswith("Default")
        ):
            return True
    return False


def _extract_parameters(command: click.Command) -> list[ParameterSpec]:
    specs: list[ParameterSpec] = []
    for parameter in command.params:
        if parameter.name in AUTO_PARAM_NAMES:
            continue
        default_value = getattr(parameter, "default", None)
        default: str | None
        if _is_missing_default(parameter, default_value):
            default = None
        else:
            default = str(default_value)
        specs.append(
            ParameterSpec(
                label=_format_parameter_label(parameter) or "",
                help_text=(getattr(parameter, "help", "") or "").strip(),
                required=getattr(parameter, "required", False),
                default=default,
            )
        )
    return specs


def _collect_click_commands(
    command: click.Command, path: Sequence[str]
) -> list[CommandSpec]:
    commands: list[CommandSpec] = []
    if isinstance(command, click.Group):
        if command.callback is not None:
            commands.append(
                CommandSpec(
                    path=list(path),
                    summary=_normalise_help(command.help),
                    parameters=_extract_parameters(command),
                )
            )
        for name, child in command.commands.items():
            commands.extend(_collect_click_commands(child, [*path, name]))
    else:
        commands.append(
            CommandSpec(
                path=list(path),
                summary=_normalise_help(command.help),
                parameters=_extract_parameters(command),
            )
        )
    return commands


def _build_pages() -> dict[str, PageSpec]:
    root_command = get_command(cli_app)
    pages: dict[str, PageSpec] = {}
    for name, command in root_command.commands.items():  # type: ignore[attr-defined]
        page = PageSpec(
            name=name, help_text=_normalise_help(getattr(command, "help", ""))
        )
        page.commands.extend(_collect_click_commands(command, [name]))
        pages[name] = page
    for page in pages.values():
        page.commands = sorted(page.commands, key=lambda item: item.path)
    return dict(sorted(pages.items(), key=lambda item: item[0]))


CLI_PAGES = _build_pages()
COMMAND_LOOKUP: dict[tuple[str, ...], CommandSpec] = {
    tuple(command.path): command
    for page in CLI_PAGES.values()
    for command in page.commands
}


def _slugify(name: str) -> str:
    return "-".join(name.lower().split())


def _render_parameters(command: CommandSpec) -> str:
    if not command.parameters:
        return '<p class="parameters-empty">No additional options.</p>'
    items = []
    for parameter in command.parameters:
        parts = [f'<span class="param-label">{escape(parameter.label)}</span>']
        if parameter.help_text:
            parts.append(
                f'<span class="param-help">{escape(parameter.help_text)}</span>'
            )
        meta = []
        if parameter.required:
            meta.append("required")
        if parameter.default is not None:
            meta.append(f"default: {escape(parameter.default)}")
        if meta:
            parts.append(
                f"<span class=\"param-meta\">({' | '.join(escape(bit) for bit in meta)})</span>"
            )
        items.append(f"<li>{' '.join(parts)}</li>")
    return '<ul class="parameters">' + "".join(items) + "</ul>"


def _render_command(command: CommandSpec) -> str:
    parameters_html = _render_parameters(command)
    summary = escape(command.summary or "")
    invocation = escape(command.invocation)
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
        "<span class=\"badge badge-density badge-density-"
        + density_key
        + f"\"><span aria-hidden=\"true\">⚙️</span>{escape(density_label)}</span>"
    )
    metadata_parts.append(
        "<span class=\"badge badge-parameters\"><span aria-hidden=\"true\">🧾</span>"
        + escape(str(parameter_count))
        + (" params" if parameter_count != 1 else " param")
        + "</span>"
    )
    if required_count:
        metadata_parts.append(
            "<span class=\"badge badge-required\"><span aria-hidden=\"true\">❗</span>"
            + escape(str(required_count))
            + (" required" if required_count != 1 else " required")
            + "</span>"
        )
    metadata_html = "".join(metadata_parts)
    command_id = "-".join(command.path)
    keyword_bits: list[str] = [command.display_name, command.summary or "", " ".join(command.path)]
    for parameter in command.parameters:
        keyword_bits.append(parameter.label)
        keyword_bits.append(parameter.help_text)
    keyword_payload = escape(" ".join(keyword_bits).lower(), quote=True)
    command_path = " ".join(escape(segment) for segment in command.path)
    return f"""
    <article class=\"command-card\" tabindex=\"0\" data-command-id=\"{escape(command_id)}\" data-command-path=\"{command_path}\" data-keywords=\"{keyword_payload}\" data-parameter-count=\"{parameter_count}\" data-required-count=\"{required_count}\">
      <header class=\"command-header\">
        <div class=\"command-title-row\">
          <h3>{escape(command.display_name)}</h3>
          <button type=\"button\" class=\"favourite-toggle\" aria-pressed=\"false\" aria-label=\"Toggle favourite for {escape(command.display_name)}\" aria-keyshortcuts=\"Shift+F\">
            <span class=\"favourite-icon\" aria-hidden=\"true\">☆</span>
            <span class=\"favourite-text\">Favourite</span>
          </button>
        </div>
        <code class=\"command-invocation\">{invocation}</code>
        <div class=\"command-meta\">{metadata_html}</div>
      </header>
      <p class=\"command-summary\">{summary}</p>
      {parameters_html}
      <form class=\"command-form\">
        <label class=\"args-label\">Additional arguments
          <input name=\"args\" type=\"text\" autocomplete=\"off\" placeholder=\"e.g. --shot /path/to/file\" />
        </label>
        <div class=\"form-actions\">
          <button type=\"submit\" class=\"run-command\" aria-keyshortcuts=\"Enter\">
            <span class=\"button-icon\" aria-hidden=\"true\">▶</span>
            <span class=\"button-label\">Run command</span>
          </button>
          <div class=\"status-cluster\">
            <span class=\"progress-indicator\" aria-hidden=\"true\" hidden></span>
            <span class=\"status\" aria-live=\"polite\"></span>
          </div>
        </div>
      </form>
      <pre id=\"{output_id}\" class=\"command-output\" hidden></pre>
    </article>
    """

def _render_page(page: PageSpec, *, is_active: bool) -> str:
    commands_html = "".join(_render_command(command) for command in page.commands)
    if not commands_html:
        commands_html = (
            '<p class="empty-page">No commands are available for this section.</p>'
        )
    help_text = escape(page.help_text or "")
    page_id = f"page-{_slugify(page.name)}"
    active_class = "active" if is_active else ""
    return f"""
    <section id=\"{page_id}\" class=\"page {active_class}\">
      <div class=\"page-header\">
        <h2>{escape(page.name.title())}</h2>
        <p class=\"page-help\">{help_text}</p>
      </div>
      {commands_html}
    </section>
    """


def _normalise_root_path(root_path: str | None) -> str:
    if not root_path or root_path == "/":
        return ""
    return root_path.rstrip("/")


def _with_root_path(root_path: str, path: str) -> str:
    if not path.startswith("/"):
        return path
    if not root_path:
        return path
    return f"{root_path}{path}"


def _render_dashboard_page(*, is_active: bool, root_path: str) -> str:
    active_class = "active" if is_active else ""
    dashboard_root = _with_root_path(root_path, "/dashboard/")
    return f"""
    <section id=\"page-dashboard\" class=\"page {active_class}\">
      <div class=\"page-header\">
        <h2>Trafalgar Dashboard</h2>
        <p class=\"page-help\">Embedded Trafalgar dashboard served from the existing FastAPI application.</p>
      </div>
      <iframe src=\"{dashboard_root}\" data-dashboard-root=\"{dashboard_root}\" title=\"Trafalgar dashboard\" loading=\"lazy\"></iframe>
    </section>
    """


def _render_index(root_path: str) -> str:
    nav_items: list[str] = []
    content_sections: list[str] = []
    for index, (name, page) in enumerate(CLI_PAGES.items()):
        page_id = f"page-{_slugify(name)}"
        active_class = "active" if index == 0 else ""
        nav_items.append(
            f'<button class="tab-button {active_class}" data-target="{page_id}">{escape(name.title())}</button>'
        )
        content_sections.append(_render_page(page, is_active=index == 0))
    nav_items.append(
        '<button class="tab-button" data-target="page-dashboard">Dashboard</button>'
    )
    content_sections.append(
        _render_dashboard_page(is_active=not content_sections, root_path=root_path)
    )

    navigation = "".join(nav_items)
    pages_html = "".join(content_sections)
    return f"""
    <!DOCTYPE html>
    <html lang=\"en\">
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>Uta Control Center</title>
        <style>
          :root {{
            color-scheme: light dark;
            --uta-bg: #0c111f;
            --uta-surface: rgba(15, 23, 42, 0.92);
            --uta-surface-alt: rgba(17, 25, 42, 0.9);
            --uta-border: rgba(148, 163, 184, 0.4);
            --uta-border-strong: rgba(96, 165, 250, 0.6);
            --uta-text: #f3f4f6;
            --uta-text-muted: rgba(226, 232, 240, 0.9);
            --uta-text-subtle: rgba(148, 163, 184, 0.88);
            --uta-accent: #60a5fa;
            --uta-accent-strong: #2563eb;
            --uta-success: #34d399;
            --uta-warning: #fbbf24;
            --uta-error: #f87171;
            --uta-card-shadow: 0 18px 36px rgba(15, 23, 42, 0.55);
          }}
          body {{
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif;
            background: var(--uta-bg);
            color: var(--uta-text);
          }}
          header.app-header {{
            padding: 1.75rem 1.5rem;
            background: linear-gradient(135deg, #1f2937, #0b1120);
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.45);
          }}
          header.app-header h1 {{
            margin: 0 0 0.35rem;
            font-size: clamp(1.75rem, 2.8vw, 2.4rem);
            letter-spacing: 0.01em;
          }}
          header.app-header p {{
            margin: 0;
            color: var(--uta-text-muted);
            max-width: 70ch;
            font-size: 0.95rem;
          }}
          .utility-bar {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            align-items: center;
            padding: 0.85rem 1.5rem;
            background: var(--uta-surface-alt);
            border-bottom: 1px solid var(--uta-border);
          }}
          .search-field {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex: 1 1 260px;
            max-width: 520px;
            padding: 0.45rem 0.85rem;
            border-radius: 999px;
            background: rgba(12, 18, 28, 0.85);
            border: 1px solid var(--uta-border);
            color: var(--uta-text-muted);
          }}
          .search-field:focus-within {{
            border-color: var(--uta-border-strong);
            box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.35);
          }}
          .search-icon {{
            font-size: 1rem;
            opacity: 0.8;
          }}
          #command-search {{
            background: transparent;
            border: none;
            color: inherit;
            flex: 1 1 auto;
            font-size: 0.95rem;
            min-width: 0;
          }}
          #command-search:focus {{
            outline: none;
          }}
          #command-search::placeholder {{
            color: var(--uta-text-subtle);
          }}
          .favourite-filter {{
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
            font-weight: 600;
            color: var(--uta-text-subtle);
          }}
          .favourite-filter input {{
            accent-color: var(--uta-accent);
            width: 1.1rem;
            height: 1.1rem;
          }}
          .favourite-filter-label span:first-child {{
            margin-right: 0.25rem;
            color: var(--uta-accent);
          }}
          nav.tab-bar {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            padding: 1rem 1.5rem;
            background: rgba(17, 25, 40, 0.92);
            border-bottom: 1px solid var(--uta-border);
          }}
          .tab-button {{
            background: transparent;
            border: 1px solid var(--uta-border);
            color: var(--uta-text-subtle);
            padding: 0.5rem 1.1rem;
            border-radius: 999px;
            cursor: pointer;
            transition: all 0.2s ease-in-out;
            font-weight: 600;
            letter-spacing: 0.02em;
          }}
          .tab-button:hover,
          .tab-button:focus-visible {{
            border-color: var(--uta-border-strong);
            color: var(--uta-text);
          }}
          .tab-button.active {{
            background: rgba(96, 165, 250, 0.2);
            color: var(--uta-text);
            border-color: var(--uta-border-strong);
            box-shadow: 0 6px 18px rgba(37, 99, 235, 0.35);
          }}
          main {{
            padding: 1.5rem;
          }}
          .page {{
            display: none;
            gap: 1.25rem;
          }}
          .page.active {{
            display: block;
          }}
          .page-header h2 {{
            margin-bottom: 0.35rem;
          }}
          .page-help {{
            margin-top: 0;
            color: var(--uta-text-subtle);
            max-width: 70ch;
          }}
          .command-card {{
            background: var(--uta-surface);
            border: 1px solid var(--uta-border);
            border-radius: 18px;
            padding: 1.35rem;
            margin-bottom: 1.25rem;
            box-shadow: var(--uta-card-shadow);
            transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
          }}
          .command-card:focus {{
            outline: 2px solid var(--uta-border-strong);
            outline-offset: 4px;
          }}
          .command-card.is-favourite {{
            border-color: var(--uta-border-strong);
            box-shadow: 0 20px 40px rgba(37, 99, 235, 0.35);
          }}
          .command-card.is-busy {{
            transform: translateY(-2px);
          }}
          .command-card.is-hidden {{
            display: none;
          }}
          .command-header {{
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            margin-bottom: 0.75rem;
          }}
          .command-title-row {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
            flex-wrap: wrap;
          }}
          .command-header h3 {{
            margin: 0;
            font-size: 1.25rem;
          }}
          .command-invocation {{
            background: rgba(10, 18, 35, 0.75);
            border-radius: 8px;
            padding: 0.4rem 0.6rem;
            font-size: 0.85rem;
            color: #93c5fd;
            width: fit-content;
            letter-spacing: 0.03em;
          }}
          .command-meta {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.4rem;
          }}
          .badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            border-radius: 999px;
            padding: 0.25rem 0.6rem;
            border: 1px solid rgba(148, 163, 184, 0.35);
            background: rgba(148, 163, 184, 0.15);
            color: var(--uta-text-subtle);
          }}
          .badge span[aria-hidden="true"] {{
            font-size: 0.85rem;
          }}
          .badge-density-none {{
            background: rgba(148, 163, 184, 0.16);
            border-color: rgba(148, 163, 184, 0.4);
            color: #cbd5f5;
          }}
          .badge-density-light {{
            background: rgba(34, 197, 94, 0.18);
            border-color: rgba(34, 197, 94, 0.45);
            color: #86efac;
          }}
          .badge-density-moderate {{
            background: rgba(59, 130, 246, 0.18);
            border-color: rgba(59, 130, 246, 0.45);
            color: #93c5fd;
          }}
          .badge-density-dense {{
            background: rgba(251, 191, 36, 0.18);
            border-color: rgba(251, 191, 36, 0.45);
            color: #fcd34d;
          }}
          .badge-parameters {{
            background: rgba(129, 140, 248, 0.18);
            border-color: rgba(129, 140, 248, 0.45);
            color: #c7d2fe;
          }}
          .badge-required {{
            background: rgba(248, 113, 113, 0.18);
            border-color: rgba(248, 113, 113, 0.45);
            color: #fecaca;
          }}
          .favourite-toggle {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            border: 1px solid var(--uta-border);
            padding: 0.3rem 0.85rem;
            background: transparent;
            color: var(--uta-text-subtle);
            cursor: pointer;
            transition: all 0.2s ease-in-out;
            font-size: 0.85rem;
            font-weight: 600;
          }}
          .favourite-toggle:hover,
          .favourite-toggle:focus-visible {{
            border-color: var(--uta-border-strong);
            color: var(--uta-text);
          }}
          .favourite-toggle.is-active {{
            background: rgba(96, 165, 250, 0.18);
            color: var(--uta-accent);
            border-color: var(--uta-border-strong);
          }}
          .favourite-toggle .favourite-icon {{
            font-size: 1rem;
          }}
          .command-summary {{
            margin-top: 0;
            margin-bottom: 0.75rem;
            color: var(--uta-text-muted);
          }}
          .parameters {{
            padding-left: 1.2rem;
            margin-top: 0;
            margin-bottom: 0.85rem;
            color: var(--uta-text-subtle);
          }}
          .parameters-empty {{
            font-style: italic;
            color: rgba(148, 163, 184, 0.85);
          }}
          .param-label {{
            font-weight: 600;
            color: #bfdbfe;
          }}
          .param-help {{
            display: block;
            margin-left: 0.25rem;
          }}
          .param-meta {{
            display: block;
            font-size: 0.8rem;
            color: rgba(148, 163, 184, 0.85);
          }}
          .command-form {{
            display: flex;
            flex-direction: column;
            gap: 0.75rem;
          }}
          .command-form .args-label {{
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
            font-weight: 600;
            color: rgba(219, 234, 254, 0.9);
          }}
          .command-form input {{
            padding: 0.55rem 0.8rem;
            border-radius: 10px;
            border: 1px solid var(--uta-border);
            background: rgba(11, 18, 32, 0.85);
            color: inherit;
          }}
          .command-form input:focus {{
            outline: 2px solid var(--uta-border-strong);
            outline-offset: 1px;
          }}
          .form-actions {{
            display: flex;
            align-items: center;
            gap: 0.85rem;
            flex-wrap: wrap;
          }}
          .run-command {{
            border: none;
            border-radius: 999px;
            padding: 0.55rem 1.4rem;
            font-weight: 600;
            cursor: pointer;
            color: #0b1120;
            background: linear-gradient(135deg, #60a5fa, #2563eb);
            transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
          }}
          .run-command:hover:not(:disabled) {{
            transform: translateY(-1px);
            box-shadow: 0 10px 20px rgba(37, 99, 235, 0.35);
          }}
          .run-command:disabled {{
            opacity: 0.6;
            cursor: wait;
            box-shadow: none;
          }}
          .button-icon {{
            font-size: 0.95rem;
          }}
          .status-cluster {{
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            min-height: 1.25rem;
          }}
          .progress-indicator {{
            width: 1rem;
            height: 1rem;
            border-radius: 50%;
            border: 2px solid rgba(148, 163, 184, 0.35);
            border-top-color: var(--uta-accent);
            animation: spin 1s linear infinite;
          }}
          .progress-indicator[hidden] {{
            display: none !important;
          }}
          .status {{
            font-size: 0.85rem;
            color: var(--uta-text-subtle);
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
          }}
          .status::before {{
            display: none;
          }}
          .status[data-state=\"running\"] {{
            color: var(--uta-text-muted);
          }}
          .status[data-state=\"running\"]::before {{
            content: '⏳';
            display: inline;
          }}
          .status[data-state=\"success\"] {{
            color: var(--uta-success);
          }}
          .status[data-state=\"success\"]::before {{
            content: '✔';
            display: inline;
          }}
          .status[data-state=\"error\"] {{
            color: var(--uta-error);
          }}
          .status[data-state=\"error\"]::before {{
            content: '⚠';
            display: inline;
          }}
          .command-output {{
            margin: 0.85rem 0 0;
            padding: 0.85rem;
            background: rgba(6, 11, 26, 0.95);
            border-radius: 14px;
            border: 1px solid rgba(30, 64, 175, 0.6);
            max-height: 320px;
            overflow: auto;
            font-family: ui-monospace, SFMono-Regular, SFMono, Menlo, Monaco, Consolas, \"Liberation Mono\", \"Courier New\", monospace;
            font-size: 0.85rem;
            white-space: pre-wrap;
          }}
          .empty-page {{
            font-style: italic;
            color: var(--uta-text-subtle);
          }}
          iframe {{
            width: 100%;
            min-height: 70vh;
            border: 1px solid rgba(96, 165, 250, 0.4);
            border-radius: 16px;
            background: rgba(15, 23, 42, 0.75);
            box-shadow: 0 18px 36px rgba(15, 23, 42, 0.45);
          }}
          @keyframes spin {{
            to {{
              transform: rotate(360deg);
            }}
          }}
          @media (max-width: 720px) {{
            .utility-bar {{
              flex-direction: column;
              align-items: stretch;
            }}
            .command-title-row {{
              align-items: flex-start;
            }}
            .form-actions {{
              align-items: stretch;
            }}
            .run-command {{
              width: 100%;
              justify-content: center;
            }}
          }}
        </style>
      </head>
      <body data-root-path=\"{escape(root_path)}\">
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
        <nav class=\"tab-bar\">
          {navigation}
        </nav>
        <main>
          {pages_html}
        </main>
        <script>
          const tabs = Array.from(document.querySelectorAll('.tab-button'));
          const pages = Array.from(document.querySelectorAll('.page'));
          function setActive(targetId) {{
            tabs.forEach((button) => {{
              button.classList.toggle('active', button.dataset.target === targetId);
            }});
            pages.forEach((page) => {{
              page.classList.toggle('active', page.id === targetId);
            }});
          }}
          tabs.forEach((button) => {{
            button.addEventListener('click', () => {{
              setActive(button.dataset.target);
            }});
          }});

          const commandCards = Array.from(document.querySelectorAll('.command-card'));
          const searchInput = document.getElementById('command-search');
          const favouritesToggle = document.getElementById('favourites-toggle');

          const storage = {{
            get(key, fallback) {{
              try {{
                const raw = localStorage.getItem(key);
                return raw === null ? fallback : raw;
              }} catch (error) {{
                console.warn('localStorage unavailable', error);
                return fallback;
              }}
            }},
            set(key, value) {{
              try {{
                localStorage.setItem(key, value);
              }} catch (error) {{
                console.warn('localStorage unavailable', error);
              }}
            }},
          }};

          const FAVOURITES_KEY = 'uta:favourites';
          const SEARCH_KEY = 'uta:search';
          const FAVOURITES_FILTER_KEY = 'uta:filter:favourites';

          const favouriteSet = (() => {{
            const raw = storage.get(FAVOURITES_KEY, '[]');
            try {{
              const parsed = JSON.parse(raw);
              if (Array.isArray(parsed)) {{
                return new Set(parsed.filter((item) => typeof item === 'string'));
              }}
            }} catch (error) {{
              console.warn('Unable to parse favourites', error);
            }}
            return new Set();
          }})();

          const persistFavourites = () => {{
            storage.set(FAVOURITES_KEY, JSON.stringify(Array.from(favouriteSet)));
          }};

          const updateFavouriteUI = (card, isFavourite) => {{
            const button = card.querySelector('.favourite-toggle');
            const icon = button ? button.querySelector('.favourite-icon') : null;
            card.classList.toggle('is-favourite', isFavourite);
            if (button) {{
              button.setAttribute('aria-pressed', String(isFavourite));
              button.classList.toggle('is-active', isFavourite);
            }}
            if (icon) {{
              icon.textContent = isFavourite ? '★' : '☆';
            }}
          }};

          function applyFilter() {{
            const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
            const favouritesOnly = favouritesToggle ? favouritesToggle.checked : false;
            commandCards.forEach((card) => {{
              const keywords = card.dataset.keywords || '';
              const matchesQuery = !query || keywords.includes(query);
              const matchesFavourite = !favouritesOnly || card.classList.contains('is-favourite');
              const visible = matchesQuery && matchesFavourite;
              card.classList.toggle('is-hidden', !visible);
              card.setAttribute('aria-hidden', String(!visible));
            }});
          }}

          commandCards.forEach((card) => {{
            const id = card.dataset.commandId;
            if (!id) {{
              return;
            }}
            const isFavourite = favouriteSet.has(id);
            updateFavouriteUI(card, isFavourite);
            const button = card.querySelector('.favourite-toggle');
            if (button) {{
              button.addEventListener('click', () => {{
                if (favouriteSet.has(id)) {{
                  favouriteSet.delete(id);
                }} else {{
                  favouriteSet.add(id);
                }}
                persistFavourites();
                updateFavouriteUI(card, favouriteSet.has(id));
                applyFilter();
              }});
            }}
          }});

          if (searchInput) {{
            const storedSearch = storage.get(SEARCH_KEY, '');
            searchInput.value = storedSearch;
            searchInput.addEventListener('input', () => {{
              storage.set(SEARCH_KEY, searchInput.value);
              applyFilter();
            }});
          }}

          if (favouritesToggle) {{
            const storedFlag = storage.get(FAVOURITES_FILTER_KEY, 'false');
            favouritesToggle.checked = storedFlag === 'true';
            favouritesToggle.addEventListener('change', () => {{
              storage.set(FAVOURITES_FILTER_KEY, String(favouritesToggle.checked));
              applyFilter();
            }});
          }}

          applyFilter();

          document.addEventListener('keydown', (event) => {{
            if (event.key === '/' && !(event.ctrlKey || event.metaKey || event.altKey)) {{
              const activeElement = document.activeElement;
              const isTyping = activeElement && ['INPUT', 'TEXTAREA'].includes(activeElement.tagName);
              if (!isTyping && searchInput) {{
                event.preventDefault();
                searchInput.focus();
                searchInput.select();
              }}
            }}
            if (event.key.toLowerCase() === 'f' && event.shiftKey && !(event.ctrlKey || event.metaKey || event.altKey)) {{
              const activeElement = document.activeElement;
              const card = activeElement ? activeElement.closest('.command-card') : null;
              if (card) {{
                event.preventDefault();
                const button = card.querySelector('.favourite-toggle');
                if (button) {{
                  button.click();
                }}
              }}
            }}
          }});

          const rootPath = document.body.dataset.rootPath || "";
          const joinWithRoot = (path) => (rootPath ? `${{rootPath}}${{path}}` : path);
          document.querySelectorAll('.command-form').forEach((form) => {{
            const card = form.closest('.command-card');
            const output = card.querySelector('.command-output');
            const status = form.querySelector('.status');
            const progress = form.querySelector('.progress-indicator');
            form.addEventListener('submit', async (event) => {{
              event.preventDefault();
              const button = form.querySelector('.run-command');
              const argsField = form.querySelector('[name=\"args\"]');
              const path = (card.dataset.commandPath || '').trim().split(/[\t\n\r\f\v ]+/).filter(Boolean);
              if (!path.length) {{
                status.textContent = 'Unknown command';
                status.dataset.state = 'error';
                return;
              }}
              button.disabled = true;
              card.classList.add('is-busy');
              status.removeAttribute('data-state');
              status.textContent = 'Running…';
              status.dataset.state = 'running';
              status.removeAttribute('title');
              if (progress) {{
                progress.hidden = false;
              }}
              output.hidden = true;
              output.textContent = '';
              try {{
                const response = await fetch(joinWithRoot('/api/run'), {{
                  method: 'POST',
                  headers: {{ 'Content-Type': 'application/json' }},
                  body: JSON.stringify({{ path, extra_args: argsField.value }}),
                }});
                const data = await response.json();
                if (!response.ok) {{
                  throw new Error(data.detail || 'Command failed');
                }}
                const trailingNewlinePattern = /\r?\n$/;
                const sanitizeSegment = (value) => {{
                  if (typeof value !== 'string') {{
                    return null;
                  }}
                  const cleaned = value.replace(trailingNewlinePattern, '');
                  return cleaned.length > 0 ? cleaned : null;
                }};

                const segments = [];
                const stdoutSegment = sanitizeSegment(data.stdout);
                if (stdoutSegment !== null) {{
                  segments.push(stdoutSegment);
                }}

                const stderrSegment = sanitizeSegment(data.stderr);
                if (stderrSegment !== null) {{
                  segments.push('\n[stderr]\n' + stderrSegment);
                }}

                segments.push(`\n(exit code: ${{data.exit_code}})`);
                output.textContent = segments.join('\n');
                output.hidden = false;
                if (data.success) {{
                  status.textContent = 'Completed';
                  status.dataset.state = 'success';
                  status.removeAttribute('title');
                }} else {{
                  status.textContent = `Failed (exit code ${{data.exit_code}})`;
                  status.dataset.state = 'error';
                  status.removeAttribute('title');
                }}
              }} catch (error) {{
                const message = error && typeof error.message === 'string' ? error.message : 'Unexpected error';
                output.textContent = message;
                output.hidden = false;
                status.textContent = 'Request error';
                status.dataset.state = 'error';
                status.title = message;
              }} finally {{
                button.disabled = false;
                card.classList.remove('is-busy');
                if (progress) {{
                  progress.hidden = true;
                }}
              }}
            }});
          }});
        </script>
      </body>
    </html>
    """
app = FastAPI(title="Uta Control Center", docs_url=None, redoc_url=None)
app.mount("/dashboard", dashboard_app)


class RunCommandRequest(BaseModel):
    path: list[str] = Field(..., description="CLI command segments to execute")
    extra_args: str = Field("", description="Raw CLI arguments appended to the command")


class RunCommandResponse(BaseModel):
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    success: bool


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    scope_root = request.scope.get("root_path", "")
    if not isinstance(scope_root, str):
        scope_root = ""
    root_path = _normalise_root_path(scope_root)
    return HTMLResponse(content=_render_index(root_path))


def _invoke_cli(arguments: Sequence[str]) -> RunCommandResponse:
    runner = CliRunner()
    result = runner.invoke(cli_app, list(arguments))
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    return RunCommandResponse(
        command=list(arguments),
        exit_code=result.exit_code,
        stdout=stdout,
        stderr=stderr,
        success=result.exit_code == 0,
    )


def _split_extra_args(extra_args: str, *, posix: bool | None = None) -> list[str]:
    if not extra_args:
        return []
    if posix is None:
        posix = os.name != "nt"
    return shlex.split(extra_args, posix=posix)


@app.post("/api/run", response_model=RunCommandResponse)
async def run_command(payload: RunCommandRequest) -> RunCommandResponse:
    command_path = tuple(payload.path)
    if command_path not in COMMAND_LOOKUP:
        raise HTTPException(status_code=404, detail="Unknown command path")
    try:
        extra_args = _split_extra_args(payload.extra_args)
    except ValueError as exc:  # pragma: no cover - user facing error
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    arguments = [*command_path, *extra_args]
    result = await asyncio.to_thread(_invoke_cli, arguments)
    return result


__all__ = [
    "app",
    "RunCommandRequest",
    "RunCommandResponse",
]
