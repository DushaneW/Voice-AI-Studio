import uuid

import pytest
from nexus_runtime.core import Core
from nexus_runtime.jobs import JobRunner
from nexus_runtime.project_copy import execute, queue
from test_workflow import wav


def setup(tmp_path):
    core = Core(tmp_path / "state")
    project = core.create_project("Source")["id"]
    asset = core.import_file(project, wav(tmp_path / "source.wav"))
    core.save_document(
        project,
        "timeline",
        {
            "clips": [
                {
                    "id": "clip",
                    "asset_id": asset["id"],
                    "start": 0,
                    "offset": 0,
                    "duration": 0.1,
                    "gain": 1,
                }
            ]
        },
        0,
    )
    job = queue(core, project, str(uuid.uuid4()), "Copy")
    runner = JobRunner(core)
    assert runner.claim_next(job_id=job["id"]) == job["id"]
    return core, project, asset, core.job(job["id"]), runner


def test_copy_independent_files_documents_and_history(tmp_path):
    core, _source, asset, job, runner = setup(tmp_path)
    transcript = core.save_transcript(
        {**job, "asset_id": asset["id"]},
        {"language": "en", "segments": [{"start": 0, "end": 0.1, "text": "hello"}]},
    )
    runner.execute(job["id"])
    result = core.job(job["id"])
    assert result["state"] == "completed", result
    target = result["result"]["project_id"]
    copied = core.active_assets(target)[0]
    assert copied["id"] != asset["id"]
    assert (
        core.asset_path(copied["id"]).read_bytes()
        == core.asset_path(asset["id"]).read_bytes()
    )
    assert (
        core.document(target, "timeline")["content"]["clips"][0]["asset_id"]
        == copied["id"]
    )
    assert len(core.document_revisions(target, "timeline")["items"]) == 1
    tr = core.db.rows("SELECT * FROM transcripts WHERE project_id=?", (target,))[0]
    assert (
        tr["id"] != transcript
        and tr["asset_id"] == copied["id"]
        and tr["job_id"] is None
    )
    core.asset_path(copied["id"]).write_bytes(b"edited")
    assert core.asset_path(asset["id"]).read_bytes()[:4] == b"RIFF"
    restarted = Core(core.db.root)
    assert restarted.job(job["id"])["state"] == "completed"
    assert restarted.asset_path(copied["id"]).read_bytes() == b"edited"


def test_idempotence_and_conflicting_request(tmp_path):
    core, project, _, job, _ = setup(tmp_path)
    assert queue(core, project, job["id"], "Copy")["id"] == job["id"]
    with pytest.raises(ValueError, match="request_id_conflict"):
        queue(core, project, job["id"], "Different")
    assert len(core.db.rows("SELECT * FROM jobs")) == 1


@pytest.mark.parametrize("failure", ["cancel", "corrupt", "database"])
def test_failure_never_publishes_partial_project(tmp_path, failure):
    core, project, asset, job, runner = setup(tmp_path)
    if failure == "corrupt":
        core.asset_path(asset["id"]).write_bytes(b"corrupt")
    if failure == "database":
        with core.db.connect() as db:
            db.execute(
                "CREATE TRIGGER fail_copy BEFORE INSERT ON document_revisions BEGIN SELECT RAISE(ABORT, 'disk_full'); END"
            )
    if failure == "cancel":

        def progress(_):
            core.cancel(job["id"])

        with pytest.raises(InterruptedError):
            execute(
                core,
                job,
                progress,
                lambda: bool(core.job(job["id"])["cancel_requested"]),
            )
    else:
        runner.execute(job["id"])
        assert core.job(job["id"])["state"] == "failed"
    assert len(core.projects()) == 1
    assert not list(core.assets.glob("copy-*"))
    assert not list(core.db.root.glob("duplicate-*"))
    assert core.document(project, "timeline")["revision"] == 1


def test_restart_cleans_interrupted_copy_only(tmp_path):
    core, _, _, job, _ = setup(tmp_path)
    orphan = core.assets / f"copy-{job['id']}-{uuid.uuid4()}.wav"
    orphan.write_bytes(b"partial")
    staging = core.db.root / f"duplicate-{job['id']}"
    staging.mkdir()
    (staging / "partial").write_bytes(b"partial")
    unrelated = core.assets / "unrelated.wav"
    unrelated.write_bytes(b"preserve")
    Core(core.db.root)
    assert not orphan.exists() and not staging.exists()
    assert unrelated.read_bytes() == b"preserve"
