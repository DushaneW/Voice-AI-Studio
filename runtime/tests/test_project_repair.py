import json

import pytest
from nexus_runtime.core import Core
from nexus_runtime.jobs import JobRunner
from nexus_runtime.project_repair import apply, queue_apply
from test_workflow import wav


def prepare(tmp_path):
    core = Core(tmp_path / "state")
    project = core.create_project("Repair", "podcast")["id"]
    core.save_document(project, "project", {"author": "Safe"}, 0)
    asset = core.import_file(project, wav(tmp_path / "source.wav"))
    transcript = core.save_transcript(
        {"id": None, "project_id": project, "asset_id": asset["id"]},
        {"language": "en", "segments": [{"start": 0, "end": 0.1, "text": "Safe"}]},
    )
    with core.db.connect() as db:
        db.execute(
            "UPDATE documents SET content='[]' WHERE project_id=? AND kind='project'",
            (project,),
        )
        db.execute("UPDATE transcripts SET segments='[{}]' WHERE id=?", (transcript,))
    plan = core.create_tts_job(project, {}, "plan_repair")
    worker = JobRunner(core)
    worker.claim_next(job_id=plan["id"])
    worker.execute(plan["id"])
    assert core.job(plan["id"])["state"] == "completed"
    return core, project, asset, transcript, plan, worker


def test_plan_read_only_apply_new_revisions_and_preserve_audio(tmp_path):
    core, project, asset, transcript, plan, worker = prepare(tmp_path)
    assert len(core.job(plan["id"])["result"]["actions"]) == 2
    assert (
        core.db.rows("SELECT content FROM documents WHERE kind='project'")[0]["content"]
        == "[]"
    )
    original = core.asset_path(asset["id"]).read_bytes()
    job = queue_apply(core, plan["id"])
    worker.claim_next(job_id=job["id"])
    worker.execute(job["id"])
    assert core.job(job["id"])["state"] == "completed"
    assert (
        core.document(project, "project")["revision"] == 2
        and core.document(project, "timeline")["revision"] == 1
    )
    tr = core.db.rows("SELECT * FROM transcripts WHERE id=?", (transcript,))[0]
    assert tr["revision"] == 2 and json.loads(tr["segments"])[0]["text"] == "Safe"
    assert core.asset_path(asset["id"]).read_bytes() == original
    assert Core(core.db.root).job(job["id"])["result"]["restored"] == 2


def test_stale_plan_never_reverts_new_work(tmp_path):
    core, project, _, transcript, plan, worker = prepare(tmp_path)
    core.save_document(project, "project", {"author": "New edit"}, 1)
    job = queue_apply(core, plan["id"])
    worker.claim_next(job_id=job["id"])
    worker.execute(job["id"])
    assert core.job(job["id"])["error"] == "repair_plan_stale"
    assert core.document(project, "project")["content"]["author"] == "New edit"
    assert (
        core.db.rows("SELECT revision FROM transcripts WHERE id=?", (transcript,))[0][
            "revision"
        ]
        == 1
    )


def test_failure_rolls_back_all_records(tmp_path):
    core, project, _, transcript, plan, worker = prepare(tmp_path)
    with core.db.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_snapshot BEFORE INSERT ON transcript_revisions BEGIN SELECT RAISE(ABORT,'disk_full'); END"
        )
    job = queue_apply(core, plan["id"])
    worker.claim_next(job_id=job["id"])
    worker.execute(job["id"])
    assert core.job(job["id"])["state"] == "failed"
    assert core.db.rows(
        "SELECT content,revision FROM documents WHERE project_id=? AND kind='project'",
        (project,),
    )[0] == {"content": "[]", "revision": 1}
    assert (
        core.db.rows("SELECT revision FROM transcripts WHERE id=?", (transcript,))[0][
            "revision"
        ]
        == 1
    )


def test_cancel_apply_commits_nothing(tmp_path):
    core, project, _, _, plan, worker = prepare(tmp_path)
    job = queue_apply(core, plan["id"])
    worker.claim_next(job_id=job["id"])
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls >= 4

    with pytest.raises(InterruptedError):
        apply(core, core.job(job["id"]), lambda _: None, cancelled)
    assert (
        core.db.rows(
            "SELECT revision FROM documents WHERE project_id=? AND kind='project'",
            (project,),
        )[0]["revision"]
        == 1
    )


def test_missing_valid_history_reported_without_inventing_data(tmp_path):
    core, _, _, transcript, plan, worker = prepare(tmp_path)
    with core.db.connect() as db:
        db.execute(
            "DELETE FROM transcript_revisions WHERE transcript_id=?", (transcript,)
        )
    repeated = core.create_tts_job(plan["project_id"], {}, "plan_repair")
    worker.claim_next(job_id=repeated["id"])
    worker.execute(repeated["id"])
    result = core.job(repeated["id"])["result"]
    assert len(result["actions"]) == 1 and result["unresolved"] == [
        {
            "category": "transcript",
            "id": transcript,
            "reason": "no_valid_revision_in_window",
        }
    ]


def test_api_requires_authentication_and_explicit_confirmation(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    core, project, _, _, plan, _ = prepare(tmp_path)
    app = create_app(core.db.root, "a" * 64)
    client = TestClient(app)
    assert client.post(f"/v1/projects/{project}/repair-plan").status_code == 401
    path = f"/v1/jobs/{plan['id']}/apply-repair"
    assert client.post(path, json={"confirmed": True}).status_code == 401
    client.headers["Authorization"] = "Bearer " + "a" * 64
    for body in ({}, {"confirmed": False}):
        assert client.post(path, json=body).status_code == 422
    assert not core.db.rows("SELECT id FROM jobs WHERE kind='apply_repair'")
    response = client.post(path, json={"confirmed": True})
    assert response.status_code == 201 and response.json()["state"] == "queued"


def test_large_project_all_records_scanned_and_repaired_in_reviewable_batches(tmp_path):
    core = Core(tmp_path / "state")
    project = core.create_project("Many transcripts")["id"]
    asset = core.import_file(project, wav(tmp_path / "source.wav", seconds=1))
    for _ in range(61):
        core.save_transcript(
            {"id": None, "project_id": project, "asset_id": asset["id"]},
            {
                "language": "en",
                "segments": [{"start": 0, "end": 1, "text": "Recover me"}],
            },
        )
    with core.db.connect() as db:
        db.execute(
            "UPDATE transcripts SET segments='[{}]' WHERE project_id=?", (project,)
        )
    worker = JobRunner(core)
    for count in (61, 11):
        planned = core.create_tts_job(project, {}, "plan_repair")
        worker.claim_next(job_id=planned["id"])
        worker.execute(planned["id"])
        result = core.job(planned["id"])["result"]
        assert result["checked"] == 61 and result["repairable_count"] == count
        assert len(result["actions"]) == min(50, count)
        assert result["remaining_repairs"] == max(0, count - 50)
        applied = queue_apply(core, planned["id"])
        worker.claim_next(job_id=applied["id"])
        worker.execute(applied["id"])
        assert core.job(applied["id"])["state"] == "completed"
    assert all(
        t["segments"][0]["text"] == "Recover me"
        for t in Core(core.db.root).transcripts()
    )
