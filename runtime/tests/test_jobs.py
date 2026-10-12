from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from nexus_runtime.core import Core
from nexus_runtime.jobs import JobRunner
from test_workflow import wav


def test_workers_cannot_claim_same_job_and_skip_cancelled(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Queue")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    cancelled = core.create_job(asset["id"])
    core.cancel(cancelled["id"])
    expected = {core.create_job(asset["id"])["id"] for _ in range(12)}
    runners = [JobRunner(core) for _ in range(20)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda runner: runner.claim_next(), runners))
    identifiers = [identifier for identifier in claimed if identifier]
    assert set(identifiers) == expected
    assert len(identifiers) == len(expected)
    assert core.job(cancelled["id"])["state"] == "cancelled"


def test_cancel_before_execution_does_not_touch_engine(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Queue")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    job = core.create_job(asset["id"])
    runner = JobRunner(core)
    assert runner.claim_next() == job["id"]
    core.cancel(job["id"])
    with patch("nexus_runtime.jobs.cached_analysis") as engine:
        runner.execute(job["id"])
        engine.assert_not_called()
    assert core.job(job["id"])["state"] == "cancelled"


def test_polling_list_is_bounded_and_omits_old_transcript_payload(tmp_path):
    import json

    core = Core(tmp_path / "data")
    project = core.create_project("Queue")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    identifiers = [core.create_job(asset["id"])["id"] for _ in range(205)]
    payload = json.dumps(
        {"transcript_id": "test", "segments": [{"text": "x" * 1_100_000}]}
    )
    with core.db.connect() as db:
        db.execute("UPDATE jobs SET result=? WHERE id=?", (payload, identifiers[-1]))
    rows = core.jobs()
    assert len(rows) == 200
    assert rows[0]["id"] == identifiers[-1]
    assert rows[0]["result"] == {"transcript_id": "test"}
    assert "options" not in rows[0]
    assert len(json.dumps(rows).encode()) < 4 * 1024 * 1024
    assert core.job(identifiers[-1])["result"][
        "segments"
    ]  # Original remains available internally.


def test_archive_preserves_outputs_dependencies_and_can_be_restored(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Queue")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    parent = core.create_job(asset["id"])
    child = core.create_job(asset["id"])
    failed = core.create_job(asset["id"])
    with core.db.connect() as db:
        db.execute(
            "UPDATE jobs SET state='completed',result=? WHERE id=?",
            ('{"peak_dbfs":0}', parent["id"]),
        )
        db.execute(
            "UPDATE jobs SET depends_on=? WHERE id=?", (parent["id"], child["id"])
        )
        db.execute("UPDATE jobs SET state='failed' WHERE id=?", (failed["id"],))
    assert core.archive_completed_jobs() == {"archived": 1}
    assert core.archive_completed_jobs() == {"archived": 0}
    assert {x["id"] for x in core.jobs()} == {child["id"], failed["id"]}
    assert [x["id"] for x in core.jobs(archived=True)] == [parent["id"]]
    assert core.job(parent["id"])["result"] == {"peak_dbfs": 0}
    assert core.asset_path(asset["id"]).exists()
    assert JobRunner(core).claim_next() == child["id"]
    assert Core(tmp_path / "data").restore_archived_jobs() == {"restored": 1}
    assert len(core.jobs()) == 3
