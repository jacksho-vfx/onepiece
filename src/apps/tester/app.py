"""Development CLI helpers for launching demo dashboards."""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from multiprocessing import Process
from typing import Iterable, Mapping

import typer

from apps.perona.app import DEFAULT_DEMO_PORT as PERONA_DEMO_PORT
from apps.perona.web.dummy_dashboard import prepare_demo_state
from apps.trafalgar.app import (
    DEFAULT_PORT as TRAFALGAR_DEFAULT_PORT,
    DEMO_DASHBOARD_TOKEN,
)
from apps.trafalgar.web.demo import prepare_demo_state as prepare_trafalgar_demo_state
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
    prepare: Callable[[], None] | None = None

    def url(self, host: str) -> str:
        """Return the full HTTP URL for the target."""

        normalised = self.path if self.path.startswith("/") else f"/{self.path}"
        return f"http://{host}:{self.port}{normalised}"


DEMO_TARGETS: tuple[DemoTarget, ...] = (
    DemoTarget(
        label="Perona demo dashboard",
        import_path="apps.perona.web.dummy_dashboard:app",
        port=PERONA_DEMO_PORT,
        prepare=prepare_demo_state,
    ),
    DemoTarget(
        label="Trafalgar demo dashboard",
        import_path="apps.trafalgar.web.demo:app",
        port=TRAFALGAR_DEMO_PORT,
        environment={"TRAFALGAR_DASHBOARD_TOKEN": DEMO_DASHBOARD_TOKEN},
        prepare=prepare_trafalgar_demo_state,
    ),
    DemoTarget(
        label="Uta CLI web app",
        import_path="apps.uta.web:app",
        port=UTA_DEFAULT_PORT,
        prepare=None,
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


def _process_ids_for_port(port: int) -> set[int]:
    """Return process identifiers bound to the given TCP port."""

    try:
        psutil = import_module("psutil")
    except ModuleNotFoundError:
        return _process_ids_for_port_without_psutil(port)

    pids: set[int] = set()
    for connection in psutil.net_connections(kind="inet"):
        local_address = connection.laddr
        if not local_address or local_address.port != port:
            continue
        if connection.pid is not None:
            pids.add(connection.pid)
    return pids


def _process_ids_for_port_without_psutil(port: int) -> set[int]:
    """Best-effort fallback for resolving listening processes without psutil."""

    system = platform.system()
    if system in {"Linux", "Darwin"}:
        try:
            result = subprocess.run(
                ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return set()
        if result.returncode not in {0, 1}:
            return set()
        return {int(line) for line in result.stdout.splitlines() if line.strip()}

    if system == "Windows":
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return set()
        pids: set[int] = set()
        port_token = f":{port}"
        for line in result.stdout.splitlines():
            if port_token not in line:
                continue
            columns = line.split()
            if len(columns) < 5:
                continue
            if columns[0].lower().startswith("tcp") and columns[3].upper() == "LISTENING":
                try:
                    pids.add(int(columns[-1]))
                except ValueError:
                    continue
        return pids

    return set()


def _terminate_processes(pids: Iterable[int]) -> tuple[list[int], list[tuple[int, str]]]:
    """Attempt to terminate processes by PID, returning successes and failures."""

    terminated: list[int] = []
    failures: list[tuple[int, str]] = []
    for pid in pids:
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            failures.append((pid, str(exc)))
        else:
            terminated.append(pid)
    return terminated, failures


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
            if target.prepare is not None:
                try:
                    target.prepare()
                except Exception as exc:  # noqa: BLE001 - surface prep failures
                    typer.echo(
                        f"Preparation for {target.label} failed: {exc}",
                        err=True,
                    )
                    raise typer.Exit(code=1) from exc
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


def _demo_ports() -> list[int]:
    """Return a sorted list of ports reserved for demo processes."""

    return sorted({target.port for target in DEMO_TARGETS})


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


@app.command("close")
def close_demos() -> None:
    """Terminate demo services bound to the configured ports."""

    ports = _demo_ports()
    if not ports:
        typer.echo("No demo ports are configured.")
        raise typer.Exit(code=0)

    psutil_available = find_spec("psutil") is not None
    psutil_warning_emitted = False
    typer.echo(
        "Checking for running demo processes on ports: "
        + ", ".join(str(port) for port in ports)
    )

    terminated_total: list[int] = []
    failures_total: list[tuple[int, str]] = []

    for port in ports:
        pids = _process_ids_for_port(port)
        if not pids:
            typer.echo(f"No processes found listening on port {port}.")
            if not psutil_available and not psutil_warning_emitted:
                typer.echo(
                    "Install the optional 'psutil' dependency for improved "
                    "process detection.",
                    err=True,
                )
                psutil_warning_emitted = True
            continue

        typer.echo(
            f"Attempting to stop processes listening on port {port}: "
            + ", ".join(str(pid) for pid in sorted(pids))
        )
        terminated, failures = _terminate_processes(pids)
        for pid in terminated:
            typer.echo(f"Sent SIGTERM to PID {pid} (port {port}).")
        for pid, reason in failures:
            typer.echo(f"Failed to terminate PID {pid} (port {port}): {reason}", err=True)
        terminated_total.extend(terminated)
        failures_total.extend((pid, reason) for pid, reason in failures)

    if terminated_total:
        typer.echo(
            "Requested termination for the following demo processes: "
            + ", ".join(str(pid) for pid in sorted(set(terminated_total)))
        )
    elif not failures_total:
        typer.echo("No demo processes were running on the configured ports.")


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
    "close_demos",
    "present",
    "DEMO_TARGETS",
    "DEMO_CREATION_HOOKS",
]
