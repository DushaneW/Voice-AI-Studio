import subprocess
import sys

import pytest
from nexus_runtime.locking import workspace_lock


def test_competing_process_rejected_and_crash_releases_lock(tmp_path):
    script = """
import sys
from pathlib import Path
from nexus_runtime.locking import workspace_lock
with workspace_lock(Path(sys.argv[1])):
    print('ready', flush=True)
    sys.stdin.read()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "ready"
        with (
            pytest.raises(RuntimeError, match="workspace_in_use"),
            workspace_lock(tmp_path),
        ):
            pass
    finally:
        child.kill()
        child.communicate(timeout=5)
    with workspace_lock(tmp_path):
        assert (tmp_path / "runtime.lock").is_file()
