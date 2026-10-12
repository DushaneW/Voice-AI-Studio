"""Linux native startup smoke on a disposable Xvfb display and data directory.

Requires a debug nexus-desktop build (source config), npm dependencies,
Xvfb, xauth, dbus-run-session and ImageMagick import. Verifies source .venv
selection with NEXUS_RUNTIME_PYTHON deliberately unset. Does not use user data.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inside", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    evidence = root / "docs" / "evidence"
    if not args.inside:
        subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1440x1000x24", "dbus-run-session", "--", os.sys.executable, __file__, "--inside"], check=True)
        return
    with tempfile.TemporaryDirectory(prefix="nexus-native-smoke-") as temporary:
        env = dict(os.environ)
        env.pop("NEXUS_RUNTIME_PYTHON", None)
        env.update(XDG_DATA_HOME=temporary, XDG_CONFIG_HOME=temporary, XDG_CACHE_HOME=temporary)
        # Run root in a container only; this is not application configuration.
        if os.geteuid() == 0:
            env["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
        processes = []
        try:
            with (evidence / "native-start-process.txt").open("w") as log:
                vite = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1"], cwd=root / "apps/desktop", env=env, stdout=log, stderr=log, start_new_session=True)
                processes.append(vite)
                deadline = time.monotonic() + 20
                while True:
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:1420", timeout=1):
                            break
                    except OSError:
                        if time.monotonic() > deadline or vite.poll() is not None:
                            raise RuntimeError("test frontend did not start")
                        time.sleep(0.2)
                app = subprocess.Popen([str(root / "target/debug/nexus-desktop")], cwd=root, env=env, stdout=log, stderr=log, start_new_session=True)
                processes.append(app)
                deadline = time.monotonic() + 25
                runtime_pid = None
                while time.monotonic() < deadline:
                    if app.poll() is not None:
                        raise RuntimeError(f"native app exited during startup: {app.returncode}")
                    listing = subprocess.check_output(["ps", "-eo", "pid=,ppid=,args="], text=True)
                    for line in listing.splitlines():
                        fields = line.strip().split(None, 2)
                        if len(fields) == 3 and fields[1] == str(app.pid) and "-m nexus_runtime" in fields[2]:
                            runtime_pid = int(fields[0])
                    if list(Path(temporary).rglob("*.sqlite3")):
                        break
                    time.sleep(0.2)
                else:
                    subprocess.run(["import", "-window", "root", str(evidence / "native-start-failed.png")], env=env)
                    details = {str(p.relative_to(temporary)): p.read_text(errors="replace")[-8000:] for p in Path(temporary).rglob("*.log")}
                    raise RuntimeError(f"source runtime did not initialize: {details}")
                time.sleep(2)
                second = subprocess.run([str(root / "target/debug/nexus-desktop")], cwd=root, env=env, stdout=log, stderr=log, timeout=10)
                assert second.returncode == 0 and app.poll() is None
                subprocess.run(["import", "-window", "root", str(evidence / "native-start.png")], check=True, env=env)
                app.terminate()
                app.wait(timeout=15)
                deadline = time.monotonic() + 10
                while runtime_pid and Path(f"/proc/{runtime_pid}").exists() and time.monotonic() < deadline:
                    time.sleep(0.2)
                assert not runtime_pid or not Path(f"/proc/{runtime_pid}").exists(), "runtime survived parent termination"
                (evidence / "native-start.json").write_text(json.dumps({"source_runtime_without_override": True, "isolated_workspace_initialized": True, "second_instance_exit": second.returncode, "runtime_exits_with_parent": bool(runtime_pid), "microphone_hardware_tested": False}, indent=2) + "\n")
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()


if __name__ == "__main__":
    main()
