import subprocess
from pathlib import Path
import structlog
from typing import Optional, List

log = structlog.get_logger(__name__)


def s5_sync(
    source: Path,
    target_bucket: str,
    context: str,
    dry_run: bool = False,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
):
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

    source_str = str(source)
    target_str = f"s3://{target_bucket}/{context}/"
    cmd += [source_str, target_str]

    log.info("running_s5cmd", command=" ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)

    uploaded = skipped = failed = 0

    for line in result.stdout.splitlines():
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

    if failed > 0:
        raise RuntimeError(f"{failed} file(s) failed to sync")
