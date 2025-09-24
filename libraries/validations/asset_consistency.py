from pathlib import Path

def check_shot_versions_local(shot_versions: dict[str, list[str]], local_base: Path) -> dict[str, list[str]]:
    """
    shot_versions: {'SH001': ['v001', 'v002']}
    Returns dict of missing files locally.
    """
    missing = {}
    for shot, versions in shot_versions.items():
        missing[shot] = []
        for v in versions:
            version_path = local_base / shot / v
            if not version_path.exists():
                missing[shot].append(v)
    return {k: v for k, v in missing.items() if v}
