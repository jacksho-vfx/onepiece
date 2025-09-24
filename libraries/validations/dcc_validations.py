"""
Validation utilities for DCC operations using Enum and file extension detection.
"""

from enum import Enum
from pathlib import Path
import subprocess
import sys

class SupportedDCC(str, Enum):
    MAYA = "maya"
    NUKE = "nuke"
    HOUDINI = "houdini"
    BLENDER = "blender"
    MAX = "3dsmax"


EXT_TO_DCC = {
    ".ma": SupportedDCC.MAYA,
    ".mb": SupportedDCC.MAYA,
    ".nk": SupportedDCC.NUKE,
    ".hip": SupportedDCC.HOUDINI,
    ".hipnc": SupportedDCC.HOUDINI,
    ".blend": SupportedDCC.BLENDER,
    ".max": SupportedDCC.MAX,
}


def validate_dcc(dcc_name: str) -> SupportedDCC:
    dcc_lower = dcc_name.lower()
    for dcc in SupportedDCC:
        if dcc.value == dcc_lower:
            return dcc
    raise ValueError(
        f"Unsupported DCC: {dcc_name}. Supported: {', '.join([d.value for d in SupportedDCC])}"
    )


def detect_dcc_from_file(file_path: str | Path) -> SupportedDCC:
    path = Path(file_path)
    ext = path.suffix.lower()
    dcc = EXT_TO_DCC.get(ext)
    if not dcc:
        raise ValueError(f"Cannot detect DCC from file extension '{ext}' for file '{file_path}'")
    return dcc

def check_dcc_installed(dcc: SupportedDCC) -> bool:
    try:
        subprocess.run([dcc.value.lower(), "--help"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def check_python_version(min_version=(3, 10)) -> bool:
    return sys.version_info >= min_version

def check_gpu_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


