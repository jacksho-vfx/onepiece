import subprocess
from enum import Enum
from pathlib import Path
import structlog
import json

log = structlog.get_logger(__name__)


class SupportedDCC(Enum):
    NUKE = "Nuke"
    MAYA = "Maya"
    BLENDER = "Blender"
    HOUDINI = "Houdini"
    MAX = "3dsMax"


# ----------------- Scene Management ----------------- #

def open_scene(dcc: SupportedDCC, file_path: Path, dry_run: bool = False):
    if not file_path.exists():
        raise FileNotFoundError(f"Scene file does not exist: {file_path}")

    cmd = []
    if dcc == SupportedDCC.NUKE:
        cmd = ["Nuke", str(file_path)]
    elif dcc == SupportedDCC.MAYA:
        cmd = ["Maya", str(file_path)]
    elif dcc == SupportedDCC.BLENDER:
        cmd = ["blender", str(file_path)]
    elif dcc == SupportedDCC.HOUDINI:
        cmd = ["houdini", str(file_path)]
    elif dcc == SupportedDCC.MAX:
        cmd = ["3dsmax", str(file_path)]
    else:
        raise ValueError(f"DCC {dcc} is not supported")

    log.info("opening_scene", dcc=dcc.value, file=str(file_path), dry_run=dry_run)
    if dry_run:
        log.info("dry_run_command", command=" ".join(cmd))
        return cmd

    subprocess.run(cmd, check=True)


def batch_open_scenes(dcc: SupportedDCC, scene_files: list[Path], dry_run: bool = False):
    for scene in scene_files:
        open_scene(dcc, scene, dry_run=dry_run)


# ----------------- Environment Checks ----------------- #

def is_dcc_installed(dcc: SupportedDCC) -> bool:
    try:
        subprocess.run([dcc.value.lower(), "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False


def check_dcc_environment(dcc: SupportedDCC) -> dict[str, bool]:
    installed = is_dcc_installed(dcc)
    python_ok = True
    gpu_ok = True
    return {
        "installed": installed,
        "python_ok": python_ok,
        "gpu_ok": gpu_ok,
    }


# ----------------- Publishing Helpers ----------------- #

def save_scene(dcc: SupportedDCC, file_path: Path, overwrite: bool = False):
    """
    Save the current scene. If overwrite is False, fail if the file exists.
    """
    if file_path.exists() and not overwrite:
        raise FileExistsError(f"Scene file already exists: {file_path}")
    
    # Currently just logging; each DCC can implement real save command
    log.info("save_scene", dcc=dcc.value, file=str(file_path), overwrite=overwrite)
    # TODO: Integrate actual DCC API calls to save the scene


def publish_scene(dcc: SupportedDCC, source: Path, target: Path, metadata: dict | None = None):
    """
    Publish a scene to a target path, optionally embedding metadata.
    """
    if not source.exists():
        raise FileNotFoundError(f"Source scene does not exist: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    # Copy the file to target (simplest publish method)
    target.write_bytes(source.read_bytes())
    log.info("scene_published", dcc=dcc.value, source=str(source), target=str(target))

    # Embed metadata as JSON sidecar
    if metadata:
        meta_file = target.with_suffix(target.suffix + ".meta.json")
        meta_file.write_text(json.dumps(metadata, indent=2))
        log.info("metadata_written", file=str(meta_file), metadata=metadata)


def create_scene_metadata(project_id: int, episode: str, scene: str, shot: str, asset: str | None = None) -> dict:
    """
    Generate standard metadata dict for a scene.
    """
    metadata = {
        "project_id": project_id,
        "episode": episode,
        "scene": scene,
        "shot": shot,
    }
    if asset:
        metadata["asset"] = asset
    return metadata
