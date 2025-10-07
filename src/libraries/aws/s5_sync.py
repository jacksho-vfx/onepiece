from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, List, Optional, Union

import structlog
from upath import UPath

log = structlog.get_logger(__name__)


PathLike = Union[UPath, Path, str]


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

    stdout_lines: list[str] = []
    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.strip()
            stdout_lines.append(line)
            if progress_callback is not None:
                progress_callback(line)
        process.stdout.close()

    process.wait()

    uploaded = skipped = failed = 0

    for line in stdout_lines:
        if "upload" in line.lower():
            uploaded += 1
        elif "skip" in line.lower():
            skipped += 1
        elif "error" in line.lower():
            failed += 1

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

    stderr_output = process.stderr.read().strip() if process.stderr else ""
    if process.stderr is not None:
        process.stderr.close()

    if process.returncode != 0:
        error_details = (
            f": {stderr_output}"
            if stderr_output
            else ". No additional error output from s5cmd."
        )
        raise RuntimeError(
            f"s5cmd sync failed with exit code {process.returncode}{error_details}"
        )

    if failed > 0:
        raise RuntimeError(f"{failed} file(s) failed to sync")
