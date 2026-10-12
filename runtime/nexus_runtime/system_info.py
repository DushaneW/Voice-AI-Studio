"""Measured hardware inventory; unavailable readings are never fabricated."""

import csv
import io
import math
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

import psutil

from .errors import DomainError

_lock = threading.Lock()
_cached = None
_checked = 0.0


def host_info():
    result = {
        "architecture": platform.machine(),
        "cpu_model": platform.processor() or None,
        "cpu_physical": None,
        "ram_total": None,
        "ram_available": None,
        "process_rss": None,
    }
    try:
        memory = psutil.virtual_memory()
        result.update(ram_total=memory.total, ram_available=memory.available)
        result["cpu_physical"] = psutil.cpu_count(logical=False)
    except (OSError, psutil.Error):
        pass
    try:
        result["process_rss"] = psutil.Process().memory_info().rss
    except (OSError, psutil.Error):
        try:
            result["process_rss"] = int(
                Path("/proc/self/statm").read_text().split()[1]
            ) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            pass
    if platform.system() == "Linux":
        try:
            with Path("/proc/cpuinfo").open() as source:
                for line in source.read(65536).splitlines():
                    if line.startswith("model name"):
                        result["cpu_model"] = line.partition(":")[2].strip()[:200]
                        break
        except OSError:
            pass
    return result


def parse_nvidia(output):
    if len(output) > 65536:
        raise DomainError("gpu_probe_output_limit")
    result = []
    for row in csv.reader(io.StringIO(output)):
        if len(row) != 4 or len(result) >= 64:
            raise DomainError("gpu_probe_invalid")
        index, name, total, free = (v.strip() for v in row)
        total_mb, free_mb = float(total), float(free)
        if (
            not index.isdecimal()
            or not math.isfinite(total_mb)
            or not math.isfinite(free_mb)
            or not 0 <= free_mb <= total_mb
            or total_mb <= 0
        ):
            raise DomainError("gpu_probe_invalid")
        result.append(
            {
                "index": int(index),
                "name": name[:200],
                "vram_total": int(total_mb * 1048576),
                "vram_free": int(free_mb * 1048576),
                "vendor": "NVIDIA",
            }
        )
    return result


def gpu_inventory():
    global _cached, _checked
    with _lock:
        if _cached is not None and time.monotonic() - _checked < 30:
            return _cached
        executable = shutil.which("nvidia-smi")
        result = {
            "state": "unavailable",
            "devices": [],
            "reason": "nvidia_probe_unavailable",
        }
        if executable:
            try:
                process = subprocess.run(
                    [
                        executable,
                        "--query-gpu=index,name,memory.total,memory.free",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                devices = parse_nvidia(process.stdout)
                result = {
                    "state": "available" if devices else "unavailable",
                    "devices": devices,
                    "reason": None if devices else "no_devices",
                }
            except (OSError, ValueError, subprocess.SubprocessError):
                result["reason"] = "nvidia_probe_failed"
        _cached, _checked = result, time.monotonic()
        return result
