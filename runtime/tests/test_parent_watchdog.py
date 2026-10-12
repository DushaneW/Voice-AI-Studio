"""Real subprocess checks for the desktop lifetime pipe contract."""

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def test_parent_eof_stops_runtime_and_releases_lock(tmp_path):
    for _ in range(2):
        env = dict(os.environ, NEXUS_DATA_DIR=str(tmp_path))
        env["PYTHONPATH"] = str(Path(__file__).parents[1])
        process = subprocess.Popen(
            [sys.executable, "-m", "nexus_runtime"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            process.stdin.write("watchdog-test-" + "x" * 48 + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
            assert line, process.stderr.read()
            port = json.loads(line)["port"]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/health",
                headers={"Authorization": "Bearer watchdog-test-" + "x" * 48},
            )
            deadline = time.monotonic() + 10
            while True:
                try:
                    with urllib.request.urlopen(request, timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            assert process.poll() is None
            process.stdin.close()
            assert process.wait(timeout=15) == 0, process.stderr.read()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()
