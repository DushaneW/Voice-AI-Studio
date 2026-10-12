import json
import subprocess
import sys

from nexus_runtime.locking import workspace_lock
from test_workflow import wav


def cli(root, *args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "nexus_runtime.cli",
            "--data-dir",
            str(root),
            *map(str, args),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def result(response):
    assert response.returncode == 0, response.stderr
    return json.loads(response.stdout)["result"]


def test_cli_import_analysis_backup_restore(tmp_path):
    root = tmp_path / "data"
    project = result(cli(root, "projects", "create", "CLI session"))
    asset = result(cli(root, "import", project["id"], wav(tmp_path / "tone.wav")))
    job = result(cli(root, "analyze", asset["id"]))
    assert job["state"] == "completed"
    assert job["result"]["peaks"]
    archive = tmp_path / "session.nexus"
    result(cli(root, "backup", project["id"], archive))
    original = archive.read_bytes()
    failed = cli(root, "backup", project["id"], archive)
    assert failed.returncode == 1
    assert json.loads(failed.stderr)["error"] == "output_exists"
    assert archive.read_bytes() == original
    restored = result(cli(root, "restore", archive))
    assert restored["id"] != project["id"]
    assert len(result(cli(root, "projects", "list"))) == 2


def test_cli_refuses_workspace_owned_by_desktop(tmp_path):
    with workspace_lock(tmp_path):
        response = cli(tmp_path, "projects", "create", "blocked")
    assert response.returncode == 1
    assert json.loads(response.stderr)["error"] == "workspace_in_use"
    assert not (tmp_path / "nexus.sqlite3").exists()
