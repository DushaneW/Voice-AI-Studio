import pytest
from nexus_runtime.core import Core
from test_workflow import wav


def session(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Keep everything")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav"))
    return core, project, asset


def test_project_restore_keeps_ids_files_and_revisions(tmp_path):
    core, project, asset = session(tmp_path)
    core.save_document(project["id"], "timeline", {"clips": []}, 0)
    path = core.asset_path(asset["id"])
    original = path.read_bytes()
    core.trash_project(project["id"])
    assert core.projects() == [] and core.active_assets() == []
    assert path.read_bytes() == original
    assert core.trash_items()["items"][0]["id"] == project["id"]
    with pytest.raises(ValueError, match="project_not_found"):
        core.create_job(asset["id"])
    core.restore_trash("project", project["id"])
    assert core.projects()[0]["id"] == project["id"]
    assert core.asset_path(asset["id"]).read_bytes() == original
    assert (
        core.document_revisions(project["id"], "timeline")["items"][0]["revision"] == 1
    )


def test_asset_restore_and_parent_restoration_order(tmp_path):
    core, project, asset = session(tmp_path)
    core.trash_asset(asset["id"])
    assert core.active_assets() == []
    assert core.projects()[0]["asset_count"] == 0
    core.trash_project(project["id"])
    with pytest.raises(ValueError, match="restore_project_first"):
        core.restore_trash("asset", asset["id"])
    core.restore_trash("project", project["id"])
    assert core.active_assets() == []
    core.restore_trash("asset", asset["id"])
    assert core.active_assets()[0]["id"] == asset["id"]


def test_active_jobs_block_trash(tmp_path):
    core, project, asset = session(tmp_path)
    job = core.create_job(asset["id"])
    with pytest.raises(ValueError, match="active_jobs"):
        core.trash_asset(asset["id"])
    with pytest.raises(ValueError, match="active_jobs"):
        core.trash_project(project["id"])
    core.cancel(job["id"])
    core.trash_project(project["id"])


def test_stale_job_creation_cannot_bypass_trash_check(tmp_path, monkeypatch):
    core, project, asset = session(tmp_path)
    # Simulate a request that read the asset before another request moved it to Trash.
    core.trash_asset(asset["id"])
    monkeypatch.setattr(core, "asset", lambda _: asset)
    with pytest.raises(ValueError, match="asset_in_trash"):
        core.create_job(asset["id"])
    core.restore_trash("asset", asset["id"])
    core.trash_project(project["id"])
    with pytest.raises(ValueError, match="project_in_trash"):
        core.create_job(asset["id"])
    assert not core.db.rows("SELECT * FROM jobs")


def test_document_references_block_asset_trash(tmp_path):
    core, project, asset = session(tmp_path)
    clip = {
        "asset_id": asset["id"],
        "offset": 0,
        "trim_start": 0,
        "trim_end": asset["duration"],
        "gain": 1,
        "fade_in": 0,
        "fade_out": 0,
    }
    core.save_document(project["id"], "timeline", {"clips": [clip]}, 0)
    with pytest.raises(ValueError, match="asset_used_in_document"):
        core.trash_asset(asset["id"])
    assert core.asset_path(asset["id"]).is_file()
