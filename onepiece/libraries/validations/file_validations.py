from pathlib import Path
import os
import shutil


def check_paths(paths: list[str | Path]) -> dict[str, dict]:
    """
    Validate each path for existence, writability, and disk space.

    Returns dict:
        path_str -> {
            "exists": bool,
            "writable": bool,
            "free_space_gb": float
        }
    """
    results = {}
    for p in paths:
        p = Path(p)
        exists = p.exists()
        writable = os.access(p, os.W_OK) if exists else False
        free_space_gb = shutil.disk_usage(p).free / 1e9 if exists else 0
        results[str(p)] = {
            "exists": exists,
            "writable": writable,
            "free_space_gb": free_space_gb,
        }
    return results


def preflight_report(paths: list[str | Path], min_free_gb: float = 1.0) -> bool:
    """
    Print a report for all paths. Returns True if all paths pass, False otherwise.
    """
    results = check_paths(paths)
    all_ok = True
    for path, info in results.items():
        status = "OK"
        if not info["exists"]:
            status = "MISSING"
            all_ok = False
        elif not info["writable"]:
            status = "NOT WRITABLE"
            all_ok = False
        elif info["free_space_gb"] < min_free_gb:
            status = f"LOW SPACE ({info['free_space_gb']:.2f} GB)"
            all_ok = False
        print(f"{path}: {status}")
    return all_ok
