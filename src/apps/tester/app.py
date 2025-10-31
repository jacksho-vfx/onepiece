"""Development CLI helpers for launching demo dashboards."""

from __future__ import annotations

import os
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from multiprocessing import Process
from typing import Mapping

import typer

from apps.perona.app import DEFAULT_DEMO_PORT as PERONA_DEMO_PORT
from apps.trafalgar.app import (
    DEFAULT_PORT as TRAFALGAR_DEFAULT_PORT,
    DEMO_DASHBOARD_TOKEN,
)
from apps.uta.app import DEFAULT_PORT as UTA_DEFAULT_PORT

DEFAULT_HOST = "127.0.0.1"
DEFAULT_LOG_LEVEL = "info"
DEFAULT_BROWSER_DELAY = 1.0
TRAFALGAR_DEMO_PORT = TRAFALGAR_DEFAULT_PORT

app = typer.Typer(
    name="tester",
    help=(
        "Launch bundled dummy dashboards and developer web apps for manual "
        "testing sessions."
    ),
)


@dataclass(frozen=True)
class DemoTarget:
    """Metadata describing a demo ASGI application to run under uvicorn."""

    label: str
    import_path: str
    port: int
    path: str = "/"
    environment: Mapping[str, str] | None = None

    def url(self, host: str) -> str:
        """Return the full HTTP URL for the target."""

        normalised = self.path if self.path.startswith("/") else f"/{self.path}"
        return f"http://{host}:{self.port}{normalised}"


DEMO_TARGETS: tuple[DemoTarget, ...] = (
    DemoTarget(
        label="Perona demo dashboard",
        import_path="apps.perona.web.dummy_dashboard:app",
        port=PERONA_DEMO_PORT,
    ),
    DemoTarget(
        label="Trafalgar demo dashboard",
        import_path="apps.trafalgar.web.demo:app",
        port=TRAFALGAR_DEMO_PORT,
        environment={"TRAFALGAR_DASHBOARD_TOKEN": DEMO_DASHBOARD_TOKEN},
    ),
    DemoTarget(
        label="Uta CLI web app",
        import_path="apps.uta.web:app",
        port=UTA_DEFAULT_PORT,
    ),
)


CreationHook = Callable[[], None]


DEMO_CREATION_HOOKS: tuple[CreationHook, ...] = ()


def _ensure_uvicorn() -> None:
    """Ensure the optional uvicorn dependency is installed."""

    try:
        import_module("uvicorn")
    except ImportError:
        typer.echo(
            "uvicorn is required to launch the demo dashboards. Install it via "
            "`pip install onepiece[uvicorn]`.",
            err=True,
        )
        raise typer.Exit(code=1)


def _serve_uvicorn(import_path: str, host: str, port: int, log_level: str) -> None:
    """Invoke ``uvicorn.run`` with the provided application import path."""

    uvicorn = import_module("uvicorn")
    uvicorn.run(import_path, host=host, port=port, reload=False, log_level=log_level)


def _run_demo_creation_hooks(skip_create: bool) -> None:
    """Execute registered creation hooks unless explicitly skipped."""

    if skip_create:
        typer.echo("Skipping demo creation hooks at caller request.")
        return

    for hook in DEMO_CREATION_HOOKS:
        hook_name = getattr(hook, "__name__", repr(hook))
        typer.echo(f"Running demo creation hook: {hook_name}")
        try:
            hook()
        except Exception as exc:  # noqa: BLE001 - surface the failure to the user
            typer.echo(
                f"Demo creation hook '{hook_name}' failed: {exc}",
                err=True,
            )
            raise typer.Exit(code=1) from exc


def _launch_demo_targets(
    *,
    host: str,
    log_level: str,
    open_browser: bool,
    browser_path: str | None,
    browser_delay: float,
) -> None:
    """Launch configured demo dashboards and supporting web apps."""

    _ensure_uvicorn()
    processes: list[tuple[DemoTarget, Process]] = []
    original_env: dict[str, tuple[bool, str]] = {}

    try:
        for target in DEMO_TARGETS:
            if target.environment:
                for key, value in target.environment.items():
                    if key not in original_env:
                        if key in os.environ:
                            original_env[key] = (True, os.environ[key])
                        else:
                            original_env[key] = (False, "")
                    os.environ.setdefault(key, value)
            typer.echo(f"Starting {target.label} on {target.url(host)}")
            process = Process(
                target=_serve_uvicorn,
                args=(target.import_path, host, target.port, log_level),
                daemon=True,
            )
            process.start()
            processes.append((target, process))

        controller = None
        if open_browser:
            try:
                controller = (
                    webbrowser.get(browser_path)
                    if browser_path is not None
                    else webbrowser.get()
                )
            except webbrowser.Error as error:
                typer.echo(
                    f"Unable to resolve a web browser controller: {error}",
                    err=True,
                )
        if controller is not None:
            if browser_delay:
                time.sleep(browser_delay)
            for target, _ in processes:
                url = target.url(host)
                try:
                    controller.open(url, new=2)
                    typer.echo(f"Opened {target.label} in a browser at {url}")
                except webbrowser.Error as error:
                    typer.echo(
                        f"Unable to open {target.label} in a browser: {error}",
                        err=True,
                    )

        typer.echo("Press Ctrl+C to stop the demo services.")
        while any(process.is_alive() for _, process in processes):
            time.sleep(0.2)
    except KeyboardInterrupt:
        typer.echo("Stopping demo services…", err=True)
    finally:
        for target, process in processes:
            if process.is_alive():
                typer.echo(f"Stopping {target.label}")
                process.terminate()
            process.join(timeout=5)

        for key, (existed, previous_value) in original_env.items():
            if existed:
                os.environ[key] = previous_value
            else:
                os.environ.pop(key, None)


@app.command("open")
def open_demos(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Interface to bind demo services to.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        DEFAULT_LOG_LEVEL,
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-browser",
        help="Open each demo surface in the default web browser.",
        show_default=True,
    ),
    browser_path: str | None = typer.Option(
        None,
        "--browser-path",
        help=(
            "Optional browser path or alias supplied to ``webbrowser.get`` "
            "when opening demo URLs."
        ),
    ),
    browser_delay: float = typer.Option(
        DEFAULT_BROWSER_DELAY,
        "--browser-delay",
        min=0.0,
        help="Seconds to wait before launching browser tabs.",
        show_default=True,
    ),
) -> None:
    """Launch all dummy dashboards and supporting web apps."""

    _launch_demo_targets(
        host=host,
        log_level=log_level,
        open_browser=open_browser,
        browser_path=browser_path,
        browser_delay=browser_delay,
    )


@app.command(
    "present",
    help=(
        "Prepare presentation-ready demo assets, then launch dashboards and "
        "control surfaces."
    ),
)
def present(
    host: str = typer.Option(
        DEFAULT_HOST,
        "--host",
        "-h",
        help="Interface to bind demo services to.",
        show_default=True,
    ),
    log_level: str = typer.Option(
        DEFAULT_LOG_LEVEL,
        "--log-level",
        help="Log level passed to uvicorn.",
        show_default=True,
    ),
    open_browser: bool = typer.Option(
        True,
        "--open-browser/--no-browser",
        help="Open each demo surface in the default web browser.",
        show_default=True,
    ),
    browser_path: str | None = typer.Option(
        None,
        "--browser-path",
        help=(
            "Optional browser path or alias supplied to ``webbrowser.get`` "
            "when opening demo URLs."
        ),
    ),
    browser_delay: float = typer.Option(
        DEFAULT_BROWSER_DELAY,
        "--browser-delay",
        min=0.0,
        help="Seconds to wait before launching browser tabs.",
        show_default=True,
    ),
    skip_create: bool = typer.Option(
        False,
        "--skip-create",
        help="Skip running presentation creation hooks before launching demos.",
        show_default=True,
    ),
) -> None:
    """Create presentation data before launching demo dashboards."""

    _run_demo_creation_hooks(skip_create=skip_create)
    _launch_demo_targets(
        host=host,
        log_level=log_level,
        open_browser=open_browser,
        browser_path=browser_path,
        browser_delay=browser_delay,
    )


__all__ = [
    "app",
    "open_demos",
    "present",
    "DEMO_TARGETS",
    "DEMO_CREATION_HOOKS",
]
