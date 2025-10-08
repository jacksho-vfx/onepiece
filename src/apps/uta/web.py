"""FastAPI application exposing a browser GUI for OnePiece commands."""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass, field
from html import escape
from typing import Sequence, Any

import click
from fastapi import FastAPI, HTTPException
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


def _extract_parameters(command: click.Command) -> list[ParameterSpec]:
    specs: list[ParameterSpec] = []
    for parameter in command.params:
        if parameter.name in AUTO_PARAM_NAMES:
            continue
        default_value = getattr(parameter, "default", None)
        default: str | None
        if default_value is None:
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
    return f"""
    <article class=\"command-card\" data-command-path=\"{' '.join(escape(segment) for segment in command.path)}\">
      <header class=\"command-header\">
        <h3>{escape(command.display_name)}</h3>
        <code class=\"command-invocation\">{invocation}</code>
      </header>
      <p class=\"command-summary\">{summary}</p>
      {parameters_html}
      <form class=\"command-form\">
        <label>Additional arguments
          <input name=\"args\" type=\"text\" autocomplete=\"off\" placeholder=\"e.g. --shot /path/to/file\" />
        </label>
        <div class=\"form-actions\">
          <button type=\"submit\" class=\"run-command\">Run command</button>
          <span class=\"status\" aria-live=\"polite\"></span>
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


def _render_dashboard_page(*, is_active: bool) -> str:
    active_class = "active" if is_active else ""
    return f"""
    <section id=\"page-dashboard\" class=\"page {active_class}\">
      <div class=\"page-header\">
        <h2>Trafalgar Dashboard</h2>
        <p class=\"page-help\">Embedded Trafalgar dashboard served from the existing FastAPI application.</p>
      </div>
      <iframe src=\"/dashboard\" title=\"Trafalgar dashboard\" loading=\"lazy\"></iframe>
    </section>
    """


def _render_index() -> str:
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
    content_sections.append(_render_dashboard_page(is_active=not content_sections))

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
          }}
          body {{
            margin: 0;
            font-family: system-ui, sans-serif;
            background: var(--uta-bg, #0f1115);
            color: #f2f5fa;
          }}
          header.app-header {{
            padding: 1.5rem;
            background: linear-gradient(135deg, #1f2937, #111827);
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
          }}
          header.app-header h1 {{
            margin: 0 0 0.5rem;
            font-size: 2rem;
          }}
          header.app-header p {{
            margin: 0;
            color: #cbd5f5;
            max-width: 60ch;
          }}
          nav.tab-bar {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            padding: 1rem 1.5rem;
            background: rgba(31, 41, 55, 0.9);
            border-bottom: 1px solid rgba(148, 163, 184, 0.25);
          }}
          .tab-button {{
            background: transparent;
            border: 1px solid rgba(148, 163, 184, 0.4);
            color: inherit;
            padding: 0.5rem 1rem;
            border-radius: 999px;
            cursor: pointer;
            transition: all 0.2s ease-in-out;
          }}
          .tab-button.active,
          .tab-button:hover {{
            background: rgba(96, 165, 250, 0.2);
            border-color: rgba(96, 165, 250, 0.6);
          }}
          main {{
            padding: 1.5rem;
          }}
          .page {{
            display: none;
            gap: 1rem;
          }}
          .page.active {{
            display: block;
          }}
          .page-header h2 {{
            margin-bottom: 0.25rem;
          }}
          .page-help {{
            margin-top: 0;
            color: rgba(203, 213, 225, 0.9);
          }}
          .command-card {{
            background: rgba(17, 24, 39, 0.75);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 16px;
            padding: 1.25rem;
            margin-bottom: 1.25rem;
            box-shadow: 0 12px 24px rgba(15, 23, 42, 0.4);
          }}
          .command-header {{
            display: flex;
            flex-direction: column;
            gap: 0.35rem;
            margin-bottom: 0.75rem;
          }}
          .command-header h3 {{
            margin: 0;
            font-size: 1.25rem;
          }}
          .command-invocation {{
            background: rgba(15, 23, 42, 0.8);
            border-radius: 6px;
            padding: 0.35rem 0.5rem;
            font-size: 0.85rem;
            color: #93c5fd;
            width: fit-content;
          }}
          .command-summary {{
            margin-top: 0;
            margin-bottom: 0.75rem;
            color: rgba(226, 232, 240, 0.85);
          }}
          .parameters {{
            padding-left: 1.25rem;
            margin-top: 0;
            margin-bottom: 0.75rem;
            color: rgba(203, 213, 225, 0.9);
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
          .command-form label {{
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
            font-weight: 600;
            color: rgba(219, 234, 254, 0.9);
          }}
          .command-form input {{
            padding: 0.5rem 0.75rem;
            border-radius: 8px;
            border: 1px solid rgba(148, 163, 184, 0.35);
            background: rgba(15, 23, 42, 0.85);
            color: inherit;
          }}
          .command-form input:focus {{
            outline: 2px solid rgba(96, 165, 250, 0.6);
            outline-offset: 1px;
          }}
          .form-actions {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
          }}
          .run-command {{
            border: none;
            border-radius: 999px;
            padding: 0.5rem 1.25rem;
            font-weight: 600;
            cursor: pointer;
            color: #0b1120;
            background: linear-gradient(135deg, #60a5fa, #2563eb);
            transition: transform 0.15s ease-in-out;
          }}
          .run-command:disabled {{
            opacity: 0.6;
            cursor: wait;
          }}
          .run-command:hover:not(:disabled) {{
            transform: translateY(-1px);
          }}
          .status {{
            font-size: 0.85rem;
            color: rgba(148, 163, 184, 0.9);
          }}
          .command-output {{
            margin: 0.75rem 0 0;
            padding: 0.75rem;
            background: rgba(2, 6, 23, 0.9);
            border-radius: 12px;
            border: 1px solid rgba(30, 64, 175, 0.6);
            max-height: 320px;
            overflow: auto;
            font-family: ui-monospace, SFMono-Regular, SFMono, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
            font-size: 0.85rem;
            white-space: pre-wrap;
          }}
          iframe {{
            width: 100%;
            min-height: 70vh;
            border: 1px solid rgba(96, 165, 250, 0.4);
            border-radius: 16px;
            background: rgba(15, 23, 42, 0.75);
            box-shadow: 0 18px 36px rgba(15, 23, 42, 0.45);
          }}
          @media (max-width: 720px) {{
            .command-header {{
              align-items: flex-start;
            }}
            .command-form label {{
              font-size: 0.9rem;
            }}
          }}
        </style>
      </head>
      <body>
        <header class=\"app-header\">
          <h1>Uta Control Center</h1>
          <p>Trigger OnePiece CLI operations through a streamlined interface and explore the Trafalgar dashboard without leaving your browser.</p>
        </header>
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
          document.querySelectorAll('.command-form').forEach((form) => {{
            const card = form.closest('.command-card');
            const output = card.querySelector('.command-output');
            const status = form.querySelector('.status');
            form.addEventListener('submit', async (event) => {{
              event.preventDefault();
              const button = form.querySelector('.run-command');
              const argsField = form.querySelector('[name="args"]');
              const path = card.dataset.commandPath.trim().split(/\s+/);
              button.disabled = true;
              status.textContent = 'Running...';
              output.hidden = true;
              output.textContent = '';
              try {{
                const response = await fetch('/api/run', {{
                  method: 'POST',
                  headers: {{ 'Content-Type': 'application/json' }},
                  body: JSON.stringify({{ path, extra_args: argsField.value }}),
                }});
                const data = await response.json();
                if (!response.ok) {{
                  throw new Error(data.detail || 'Command failed');
                }}
                const segments = [];
                if (data.stdout) {{
                  segments.push(data.stdout.trim());
                }}
                if (data.stderr) {{
                  segments.push('\n[stderr]\n' + data.stderr.trim());
                }}
                segments.push(`\n(exit code: ${{data.exit_code}})`);
                output.textContent = segments.join('\n');
                output.hidden = false;
                status.textContent = 'Completed';
              }} catch (error) {{
                output.textContent = error.message;
                output.hidden = false;
                status.textContent = 'Error';
              }} finally {{
                button.disabled = false;
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


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(content=_render_index())


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
    )


@app.post("/api/run", response_model=RunCommandResponse)
async def run_command(payload: RunCommandRequest) -> RunCommandResponse:
    command_path = tuple(payload.path)
    if command_path not in COMMAND_LOOKUP:
        raise HTTPException(status_code=404, detail="Unknown command path")
    try:
        extra_args = shlex.split(payload.extra_args) if payload.extra_args else []
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
