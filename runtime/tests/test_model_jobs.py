import json
import sqlite3
import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.core import Core
from nexus_runtime.jobs import JobRunner
from nexus_runtime.model_jobs import queue
from nexus_runtime.models import ModelManager
from nexus_runtime.notifications import events, search
from test_models import DATA, Response, manager
from test_workflow import wav


def setup(tmp_path):
    core = Core(tmp_path)
    fixture = manager(tmp_path)
    models = ModelManager(core.db, list(fixture.catalog.values()))
    return core, models, JobRunner(core, models)


def run(worker, job):
    assert worker.claim_next(job_id=job["id"]) == job["id"]
    worker.execute(job["id"])
    return worker.core.job(job["id"])


def test_global_model_job_idempotence_real_download_events_and_archive(tmp_path):
    core, models, worker = setup(tmp_path)
    job = queue(core, models, "test", "install")
    assert queue(core, models, "test", "install")["id"] == job["id"]
    with pytest.raises(ValueError, match="model_operation_in_progress"):
        queue(core, models, "test", "repair")
    assert core.projects() == [] and job["project_id"] is None
    with patch("urllib.request.urlopen", return_value=Response(DATA)):
        result = run(worker, job)
    assert result["state"] == "completed" and result["result"]["verified"] is True
    assert (models.directory("test") / "model.bin").read_bytes() == DATA
    assert [e["state"] for e in events(core, job["id"])["items"]] == [
        "completed",
        "running",
        "queued",
    ]
    assert search(core)["items"][0]["job_id"] == job["id"]
    assert core.jobs()[0]["model_id"] == "test"
    assert models.list()[0]["job_id"] == job["id"]
    assert core.archive_completed_jobs()["archived"] == 1
    assert core.jobs() == [] and len(core.jobs(archived=True)) == 1
    assert core.restore_archived_jobs()["restored"] == 1


def test_corrupt_download_retries_as_new_durable_job(tmp_path):
    core, models, worker = setup(tmp_path)
    job = queue(core, models, "test", "install")
    with patch("urllib.request.urlopen", return_value=Response(b"x" * len(DATA))):
        result = run(worker, job)
    assert result["state"] == "failed" and result["error"] == "model_checksum_mismatch"
    retry = core.retry(job["id"])
    assert retry["id"] != job["id"] and retry["project_id"] is None
    with patch("urllib.request.urlopen", return_value=Response(DATA)):
        assert run(worker, retry)["state"] == "completed"
    assert len(search(core)["items"]) == 2


def test_restart_and_policy_change_prevent_unapproved_network(tmp_path):
    core, models, worker = setup(tmp_path)
    job = queue(core, models, "test", "install")
    worker.claim_next(job_id=job["id"])
    core = Core(tmp_path)
    assert core.job(job["id"])["state"] == "interrupted"
    retry = core.retry(job["id"])
    with core.db.connect() as db:
        db.execute("INSERT INTO settings VALUES('model_downloads_allowed','false')")
    with patch(
        "urllib.request.urlopen", side_effect=AssertionError("network forbidden")
    ):
        result = run(JobRunner(core, models), retry)
    assert result["error"] == "model_downloads_disabled"
    assert search(core)["items"][-1]["state"] == "interrupted"


def test_cancellation_pauses_active_download_without_publishing(tmp_path):
    core, models, worker = setup(tmp_path)
    job = queue(core, models, "test", "install")
    reading, release = threading.Event(), threading.Event()

    class Blocked(Response):
        def read(self, size=-1):
            reading.set()
            assert release.wait(5)
            return super().read(size)

    with patch("urllib.request.urlopen", return_value=Blocked(DATA)):
        worker.claim_next(job_id=job["id"])
        thread = threading.Thread(target=worker.execute, args=(job["id"],))
        thread.start()
        try:
            assert reading.wait(5)
            core.cancel(job["id"])
            # The worker checks cancellation while the downloader awaits bytes.
            models.thread.join(0.2)
            release.set()
            thread.join(5)
            assert not thread.is_alive()
        finally:
            release.set()
            thread.join(5)
    assert core.job(job["id"])["state"] == "cancelled"
    assert models.list()[0]["state"] == "paused"
    assert not (models.root / "test" / "model.bin").exists()


def test_local_verification_uses_queue_with_downloads_disabled(tmp_path):
    core, models, worker = setup(tmp_path)
    folder = models.root / "test"
    folder.mkdir()
    (folder / "model.bin").write_bytes(DATA)
    models.state("test", "installed")
    with core.db.connect() as db:
        db.execute("INSERT INTO settings VALUES('model_downloads_allowed','false')")
    job = queue(core, models, "test", "verify")
    with patch(
        "urllib.request.urlopen", side_effect=AssertionError("network forbidden")
    ):
        assert run(worker, job)["state"] == "completed"


def test_catalog_change_rejected_before_download_and_api_uses_jobs(tmp_path):
    core, models, worker = setup(tmp_path)
    job = queue(core, models, "test", "install")
    models.catalog["test"]["revision"] = "changed"
    with patch(
        "urllib.request.urlopen", side_effect=AssertionError("network forbidden")
    ):
        assert run(worker, job)["error"] == "model_catalog_changed"
    app = create_app(tmp_path / "api", "a" * 64)
    client = TestClient(app)
    assert client.post("/v1/models/whisper-tiny/install").status_code == 401
    client.headers["Authorization"] = "Bearer " + "a" * 64
    with patch(
        "urllib.request.urlopen", side_effect=AssertionError("request must only queue")
    ):
        response = client.post("/v1/models/whisper-tiny/install")
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        assert client.get(f"/v1/jobs/{job_id}/status").json()["state"] == "queued"
        assert client.post(f"/v1/jobs/{job_id}/events", json={}).status_code == 200
        client.post("/v1/models/whisper-tiny/cancel")
        assert client.get(f"/v1/jobs/{job_id}/status").json()["state"] == "cancelled"


def test_migration_preserves_job_children_and_prevents_orphan_media_jobs(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Migration")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"])
    run(JobRunner(core), job)
    transcript = core.save_transcript(
        job, {"language": "en", "segments": [{"start": 0, "end": 1, "text": "Persist"}]}
    )
    core.archive_completed_jobs()
    with core.db.connect() as db:
        db.execute("DROP INDEX jobs_active_model")
        db.execute("PRAGMA user_version=10")
        before = {
            table: [tuple(r) for r in db.execute(f"SELECT * FROM {table}")]
            for table in (
                "jobs",
                "transcripts",
                "job_archive",
                "job_events",
                "notifications",
            )
        }
    reopened = Core(tmp_path)
    with reopened.db.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 11
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        for table, records in before.items():
            assert [tuple(r) for r in db.execute(f"SELECT * FROM {table}")] == records
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO jobs(id,kind,state,created,updated) VALUES('orphan','tts','queued','','')"
            )
    assert reopened.transcripts()[0]["id"] == transcript
    assert search(reopened)["unread"] == 1


def test_migration_failure_rolls_back_without_cascading_children(tmp_path):
    core, models, _ = setup(tmp_path)
    job = queue(core, models, "test", "install")
    with sqlite3.connect(core.db.path) as db:
        db.execute("DROP INDEX jobs_active_model")
        db.execute("UPDATE jobs SET project_id='nonexistent' WHERE id=?", (job["id"],))
        db.execute("PRAGMA user_version=10")
    with pytest.raises(RuntimeError, match="foreign_key_error"):
        Core(tmp_path)
    with sqlite3.connect(core.db.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 10
        assert (
            db.execute(
                "SELECT count(*) FROM job_events WHERE job_id=?", (job["id"],)
            ).fetchone()[0]
            == 1
        )
        assert (
            json.loads(
                db.execute(
                    "SELECT options FROM jobs WHERE id=?", (job["id"],)
                ).fetchone()[0]
            )["model_id"]
            == "test"
        )
