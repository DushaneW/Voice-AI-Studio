import subprocess
from types import SimpleNamespace

import pytest
from nexus_runtime import system_info


def test_measured_host_has_ram_and_architecture():
    result = system_info.host_info()
    assert (
        result["ram_total"] > 0 and 0 <= result["ram_available"] <= result["ram_total"]
    )
    assert result["architecture"] and result["process_rss"] > 0


def test_parse_devices_rejects_invalid_measurements():
    result = system_info.parse_nvidia(
        "0, Device A, 8192, 4096\n1, Device B, 16384, 8000\n"
    )
    assert len(result) == 2 and result[0]["vram_total"] == 8192 * 1048576
    for line in ["0, Device, NaN, 0", "0, Device, 100, 101"]:
        with pytest.raises(ValueError):
            system_info.parse_nvidia(line)


def test_probe_cache_and_timeout(monkeypatch):
    monkeypatch.setattr(system_info, "_cached", None)
    monkeypatch.setattr(system_info, "_checked", 0)
    monkeypatch.setattr(system_info.shutil, "which", lambda _: "/fake/nvidia-smi")
    calls = []

    def run(args, **options):
        calls.append(args)
        assert options["timeout"] == 2
        return SimpleNamespace(stdout="0, GPU, 1000, 500")

    monkeypatch.setattr(system_info.subprocess, "run", run)
    assert system_info.gpu_inventory()["devices"][0]["name"] == "GPU"
    assert system_info.gpu_inventory()["state"] == "available" and len(calls) == 1
    monkeypatch.setattr(system_info, "_cached", None)

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 2)

    monkeypatch.setattr(system_info.subprocess, "run", fail)
    assert system_info.gpu_inventory()["reason"] == "nvidia_probe_failed"
