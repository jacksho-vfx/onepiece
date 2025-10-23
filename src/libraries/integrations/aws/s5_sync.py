from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional, Union

import structlog

log = structlog.get_logger(__name__)


PathLike = Union[Path, str]


def _normalise_path(path: PathLike) -> str:
    path_str = str(path)
    if path_str.endswith("/"):
        return path_str
    return f"{path_str.rstrip('/')}/"


def s5_sync(
    source: PathLike,
    destination: PathLike,
    dry_run: bool = False,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    progress_callback: Callable[[str], None] | None = None,
    profile: Optional[str] = None,
) -> None:
    """
    Sync a folder to/from S3 bucket using s5cmd with dry-run and filters.
    Logs a summary report after completion.
    """

    cmd = ["s5cmd", "sync"]

    if include:
        for pattern in include:
            cmd += ["--include", pattern]
    if exclude:
        for pattern in exclude:
            cmd += ["--exclude", pattern]

    if dry_run:
        cmd.append("--dry-run")

    source_str = _normalise_path(source)
    destination_str = _normalise_path(destination)
    cmd += [source_str, destination_str]

    log.info("running_s5cmd", command=" ".join(cmd))

    popen_env = None
    if profile is not None:
        popen_env = os.environ.copy()
        popen_env["AWS_PROFILE"] = profile

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=popen_env,
    )

    stderr_lines: list[str] = []
    stderr_thread: threading.Thread | None = None

    if process.stderr is not None:
        stderr_stream = process.stderr

        def _capture_stderr() -> None:
            for raw_line in stderr_stream:
                stderr_lines.append(raw_line)

        stderr_thread = threading.Thread(target=_capture_stderr, daemon=True)
        stderr_thread.start()

    uploaded = skipped = failed = 0

    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if progress_callback is not None:
                progress_callback(line)

            lowered_line = line.lower()
            if "upload" in lowered_line:
                uploaded += 1
            elif "skip" in lowered_line:
                skipped += 1
            elif "error" in lowered_line:
                failed += 1

    process.wait()

    if stderr_thread is not None:
        stderr_thread.join()

    stderr_output = "".join(stderr_lines)

    total = uploaded + skipped + failed
    log.info(
        "s5cmd_summary",
        total_files=total,
        uploaded=uploaded,
        skipped=skipped,
        failed=failed,
    )

    print("--- S5CMD Sync Summary ---")
    print(f"Total files: {total}")
    print(f"Uploaded:   {uploaded}")
    print(f"Skipped:    {skipped}")
    print(f"Failed:     {failed}")

    if process.returncode != 0:
        stderr_message = stderr_output.strip()
        error_details = (
            f": {stderr_message}"
            if stderr_message
            else ". No additional error output from s5cmd."
        )
        raise RuntimeError(
            f"s5cmd sync failed with exit code {process.returncode}{error_details}"
        )

    if failed > 0:
        raise RuntimeError(f"{failed} file(s) failed to sync")
