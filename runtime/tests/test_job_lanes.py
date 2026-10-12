"""Model operations and media jobs use independent lanes."""

import pytest
from nexus_runtime.jobs import JobRunner
from nexus_runtime.model_jobs import queue
from test_model_jobs import setup
from test_workflow import wav


def test_media_job_is_claimable_while_a_different_model_downloads(tmp_path):
    core, models, runner = setup(tmp_path)
    project = core.create_project("Lanes")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    model_job = queue(core, models, "test", "install")
    media_job = core.create_job(asset["id"])  # analysis: no model involved

    assert runner.claim_next(lane="models") == model_job["id"]
    # The download is "running" and never finishes in this test; media still runs.
    assert runner.claim_next(lane="media") == media_job["id"]


def test_lanes_do_not_take_each_others_jobs(tmp_path):
    core, models, runner = setup(tmp_path)
    project = core.create_project("Lanes")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    model_job = queue(core, models, "test", "install")
    media_job = core.create_job(asset["id"])

    assert runner.claim_next(lane="media") == media_job["id"]
    assert runner.claim_next(lane="media") is None
    assert runner.claim_next(lane="models") == model_job["id"]
    assert runner.claim_next(lane="models") is None


def test_media_job_waits_for_operation_on_the_same_model(tmp_path):
    core, models, runner = setup(tmp_path)
    project = core.create_project("Lanes")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    install = queue(core, models, "test", "install")
    dependent = core.create_job(asset["id"], "tts", {"model_id": "test"})
    unrelated = core.create_job(asset["id"], "tts", {"model_id": "other"})

    assert runner.claim_next(lane="media") == unrelated["id"]
    assert runner.claim_next(lane="media") is None  # blocked by queued install
    assert runner.claim_next(lane="models") == install["id"]
    assert runner.claim_next(lane="media") is None  # still running
    with core.db.connect() as db:
        db.execute("UPDATE jobs SET state='completed' WHERE id=?", (install["id"],))
    assert runner.claim_next(lane="media") == dependent["id"]


def test_unknown_lane_is_rejected(tmp_path):
    core, _, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="invalid_lane"):
        JobRunner(core).claim_next(lane="gpu")
