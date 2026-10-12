import array
import math
import time
import wave

import pytest
from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.core import Core
from nexus_runtime.database import Database
from nexus_runtime.jobs import JobRunner
from nexus_runtime.media import MediaError, analyze, probe

TOKEN = "test-only-" + "a" * 40


def wav(path, seconds=0.1):
    samples = array.array(
        "h",
        [
            int(16000 * math.sin(2 * math.pi * 440 * i / 24000))
            for i in range(int(24000 * seconds))
        ],
    )
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(24000)
        output.writeframes(samples.tobytes())
    return path


@pytest.fixture
def client(tmp_path):
    with TestClient(
        create_app(tmp_path / "state", TOKEN),
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as c:
        yield c


def test_full_project_import_analyze_playback_flow(client, tmp_path):
    project = client.post("/v1/projects", json={"name": "Session"}).json()
    imported = client.post(
        "/v1/assets/import",
        json={"project_id": project["id"], "path": str(wav(tmp_path / "tone.wav"))},
    )
    assert imported.status_code == 201
    asset = imported.json()
    client.post("/v1/jobs", json={"asset_id": asset["id"]}).raise_for_status()
    for _ in range(200):
        jobs = client.get("/v1/jobs").json()
        if jobs[0]["state"] in {"completed", "failed"}:
            break
        time.sleep(0.01)
    assert jobs[0]["state"] == "completed"
    assert 0 < len(jobs[0]["result"]["peaks"]) <= 640
    assert -7 < jobs[0]["result"]["peak_dbfs"] < -6
    response = client.get(f"/v1/assets/{asset['id']}/audio")
    assert response.content[:4] == b"RIFF"
    assert client.get("/v1/projects").json()[0]["asset_count"] == 1


def test_auth_and_origin(client):
    assert client.get("/health", headers={"Authorization": ""}).status_code == 401
    assert (
        client.get("/health", headers={"Origin": "https://example.com"}).status_code
        == 403
    )
    assert client.get("/health").json()["status"] == "ready"


def test_validation_errors(client):
    assert client.post("/v1/projects", json={"name": " "}).status_code == 409
    assert (
        client.post("/v1/projects", json={"name": "A", "extra": 1}).status_code == 422
    )
    assert client.get("/v1/assets", params={"project_id": "missing"}).status_code == 404
    assert client.post("/v1/jobs", json={"asset_id": "missing"}).status_code == 404


def test_no_path_traversal_or_shell_interpretation(client, tmp_path):
    p = client.post("/v1/projects", json={"name": "$(touch hacked)"}).json()
    assert (
        client.post(
            "/v1/assets/import", json={"project_id": p["id"], "path": "; rm -rf /"}
        ).status_code
        == 422
    )
    assert client.get("/v1/assets/../../etc/passwd/audio").status_code == 404


def test_database_persists_and_recovers(tmp_path):
    c = Core(tmp_path / "root")
    p = c.create_project("Persistent")
    a = c.import_file(p["id"], wav(tmp_path / "a.wav"))
    j = c.create_job(a["id"])
    with c.db.connect() as db:
        db.execute("UPDATE jobs SET state='running' WHERE id=?", (j["id"],))
    restarted = Core(tmp_path / "root")
    assert restarted.projects()[0]["name"] == "Persistent"
    assert restarted.job(j["id"])["state"] == "interrupted"


def test_future_schema_rejected(tmp_path):
    c = Core(tmp_path / "state")
    with c.db.connect() as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(RuntimeError):
        Database(tmp_path / "state")


def test_cancel_queued_and_retry(tmp_path):
    c = Core(tmp_path / "state")
    p = c.create_project("A")
    a = c.import_file(p["id"], wav(tmp_path / "a.wav"))
    j = c.create_job(a["id"])
    c.cancel(j["id"])
    assert c.job(j["id"])["state"] == "cancelled"
    assert c.retry(j["id"])["state"] == "queued"


def test_cancel_running(tmp_path):
    c = Core(tmp_path / "state")
    p = c.create_project("A")
    a = c.import_file(p["id"], wav(tmp_path / "a.wav"))
    j = c.create_job(a["id"])
    with c.db.connect() as db:
        db.execute(
            "UPDATE jobs SET state='running',cancel_requested=1 WHERE id=?", (j["id"],)
        )
    JobRunner(c).execute(j["id"])
    assert c.job(j["id"])["state"] == "cancelled"


def test_invalid_and_truncated_media(tmp_path):
    p = tmp_path / "invalid.wav"
    p.write_bytes(b"bad")
    with pytest.raises(MediaError):
        probe(p)
    wav(p)
    p.write_bytes(p.read_bytes()[:-5])
    with pytest.raises(MediaError):
        probe(p)


def test_silence_and_cancellation(tmp_path):
    p = tmp_path / "silence.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(bytes(4800))
    r = analyze(p, lambda _: None, lambda: False)
    assert r["peak_dbfs"] is None and r["rms_dbfs"] is None
    with pytest.raises(InterruptedError):
        analyze(p, lambda _: None, lambda: True)


def test_settings_persist(client):
    r = client.put(
        "/v1/settings",
        json={"language": "pl", "workspace": "media", "inspector": False},
    )
    assert r.status_code == 200
    assert client.get("/v1/settings").json()["language"] == "pl"


def test_delete_rejects_active_jobs(tmp_path):
    c = Core(tmp_path / "state")
    p = c.create_project("A")
    a = c.import_file(p["id"], wav(tmp_path / "a.wav"))
    c.create_job(a["id"])
    with pytest.raises(ValueError, match="active_jobs"):
        c.delete_project(p["id"])


def test_import_failure_does_not_leave_assets(tmp_path):
    c = Core(tmp_path / "state")
    p = c.create_project("A")
    source = tmp_path / "bad.wav"
    source.write_bytes(b"bad")
    with pytest.raises(MediaError):
        c.import_file(p["id"], source)
    assert list(c.assets.iterdir()) == []


def test_diagnostics_has_no_auth_or_project_content(client):
    client.post("/v1/projects", json={"name": "PRIVATE_PROJECT_CANARY"})
    r = client.get("/v1/diagnostics")
    assert r.status_code == 200
    assert TOKEN not in r.text and "PRIVATE_PROJECT_CANARY" not in r.text


def test_symlink_import_rejected(tmp_path):
    c = Core(tmp_path / "state")
    p = c.create_project("A")
    source = wav(tmp_path / "source.wav")
    link = tmp_path / "link.wav"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(MediaError):
        c.import_file(p["id"], link)
