"""Looks at the machine so the setup wizard can recommend a model size."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass

import psutil


@dataclass
class Hardware:
    ram_gb: float
    cpu_cores: int
    gpu: str | None  # human-readable name, or None
    gpu_gb: float  # memory usable by the GPU; 0 when there is none
    system: str

    def to_dict(self) -> dict:
        return asdict(self)


def detect() -> Hardware:
    ram_gb = round(psutil.virtual_memory().total / 2**30, 1)
    cores = psutil.cpu_count(logical=False) or psutil.cpu_count() or 1
    system = platform.system()
    gpu, gpu_gb = _nvidia()
    if gpu is None and system == "Darwin" and platform.machine() == "arm64":
        # Apple Silicon shares system memory with the GPU.
        gpu, gpu_gb = "Apple Silicon", ram_gb
    return Hardware(ram_gb=ram_gb, cpu_cores=cores, gpu=gpu, gpu_gb=gpu_gb, system=system)


def _nvidia() -> tuple[str | None, float]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, 0.0
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout
        name, memory_mb = out.strip().splitlines()[0].rsplit(",", 1)
        return name.strip(), round(float(memory_mb) / 1024, 1)
    except (subprocess.SubprocessError, ValueError, IndexError, OSError):
        return None, 0.0
