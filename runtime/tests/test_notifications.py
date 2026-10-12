import sqlite3

import pytest
from nexus_runtime.core import Core
from nexus_runtime.jobs import JobRunner
from nexus_runtime.notifications import events, mark_read, search


def test_events_and_notifications_survive_restart_without_duplicates(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Project")["id"]
    job = core.create_tts_job(project, {}, "validate_project")
    runner = JobRunner(core)
    runner.claim_next(job_id=job["id"])
    runner.execute(job["id"])
    assert [x["state"] for x in events(core, job["id"])["items"]] == [
        "completed",
        "running",
        "queued",
    ]
    assert search(core)["unread"] == 1
    item = search(core)["items"][0]
    mark_read(core, item["id"])
    restarted = Core(tmp_path)
    assert search(restarted)["unread"] == 0
    assert len(search(restarted)["items"]) == 1
    assert search(restarted, unread_only=True)["items"] == []


def test_interruption_notification_and_trash_visibility(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Interrupted")["id"]
    job = core.create_tts_job(project, {}, "validate_project")
    JobRunner(core).claim_next(job_id=job["id"])
    core = Core(tmp_path)
    item = search(core)["items"][0]
    assert item["state"] == "interrupted"
    core.trash_project(project)
    assert search(core)["unread"] == 0
    with pytest.raises(ValueError, match="not_found"):
        events(core, job["id"])
    with pytest.raises(ValueError, match="not_found"):
        mark_read(core, item["id"])


def test_notifications_are_atomic_and_paginated(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Many")["id"]
    for _ in range(53):
        job = core.create_tts_job(project, {})
        core.cancel(job["id"])
    first = search(core)
    second = search(core, first["next_cursor"])
    assert len(first["items"]) == 50 and len(second["items"]) == 3
    assert len({n["id"] for n in first["items"] + second["items"]}) == 53
    job = core.create_tts_job(project, {})
    with core.db.connect() as db:
        db.execute(
            "CREATE TRIGGER fail_notification BEFORE INSERT ON notifications BEGIN SELECT RAISE(ABORT, 'disk_full'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        core.cancel(job["id"])
    assert core.job(job["id"])["state"] == "queued"
    assert [e["state"] for e in events(core, job["id"])["items"]] == ["queued"]
