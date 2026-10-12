import sqlite3

import pytest
from nexus_runtime.core import Core
from nexus_runtime.database import Database


def test_restore_is_new_revision_and_stale_restore_does_not_write(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Recovery")["id"]
    core.save_document(project, "timeline", {"clips": [], "sample_rate": 24000}, 0)
    core.save_document(project, "timeline", {"clips": [], "sample_rate": 48000}, 1)
    result = core.restore_document(project, "timeline", 1, 2)
    assert result["revision"] == 3 and result["content"]["sample_rate"] == 24000
    with pytest.raises(ValueError, match="revision_conflict"):
        core.restore_document(project, "timeline", 2, 2)
    assert len(core.document_revisions(project, "timeline")["items"]) == 3
    assert Core(tmp_path).document(project, "timeline")["revision"] == 3


def test_upgrade_v4_snapshots_existing_document_and_preserves_models(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Existing")["id"]
    core.save_document(project, "timeline", {"clips": []}, 0)
    with core.db.connect() as db:
        db.execute("INSERT INTO models(id,state) VALUES('installed-test','installed')")
        db.execute("DROP TABLE document_revisions")
        for trigger in [
            "jobs_active_project",
            "jobs_active_asset",
            "assets_active_project",
            "documents_active_insert",
            "documents_active_update",
        ]:
            db.execute(f"DROP TRIGGER {trigger}")
        db.execute("DROP TABLE project_trash")
        db.execute("DROP TABLE asset_trash")
        db.execute("DROP TABLE job_archive")
        db.execute("DROP TRIGGER transcript_snapshot_insert")
        db.execute("DROP TRIGGER transcript_snapshot_update")
        db.execute("DROP TABLE transcript_revisions")
        db.execute("DROP TABLE import_receipts")
        for trigger in ["job_event_insert", "job_event_update", "job_notification"]:
            db.execute(f"DROP TRIGGER {trigger}")
        db.execute("DROP TABLE notifications")
        db.execute("DROP TABLE job_events")
        db.execute("DROP INDEX IF EXISTS jobs_active_model")
        db.execute("PRAGMA user_version=4")
    upgraded = Core(tmp_path)
    assert upgraded.document_revisions(project, "timeline")["items"][0]["revision"] == 1
    assert (
        upgraded.db.rows("SELECT state FROM models WHERE id='installed-test'")[0][
            "state"
        ]
        == "installed"
    )
    Database(tmp_path)
    assert len(upgraded.document_revisions(project, "timeline")["items"]) == 1
    with sqlite3.connect(upgraded.db.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 11
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_revisions_are_project_scoped_and_paginated(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("History")["id"]
    other = core.create_project("Other")["id"]
    for revision in range(53):
        core.save_document(project, "timeline", {"clips": []}, revision)
    first = core.document_revisions(project, "timeline")
    second = core.document_revisions(project, "timeline", first["next_cursor"])
    assert [x["revision"] for x in first["items"] + second["items"]] == list(
        range(53, 0, -1)
    )
    with pytest.raises(ValueError, match="not_found"):
        core.restore_document(other, "timeline", 1, 0)
    core.delete_project(project)
    assert not core.db.rows("SELECT * FROM document_revisions")


def test_snapshot_failure_rolls_back_document_update(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Atomic")["id"]
    core.save_document(project, "timeline", {"clips": [], "sample_rate": 24000}, 0)
    with core.db.connect() as db:
        db.execute(
            "CREATE TRIGGER simulate_full_disk BEFORE INSERT ON document_revisions BEGIN SELECT RAISE(ABORT, 'snapshot_write_failed'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="snapshot_write_failed"):
        core.save_document(project, "timeline", {"clips": [], "sample_rate": 48000}, 1)
    document = core.document(project, "timeline")
    assert document["revision"] == 1 and document["content"]["sample_rate"] == 24000


def test_concurrent_save_has_one_winner_and_one_snapshot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    core = Core(tmp_path)
    project = core.create_project("Conflict")["id"]
    core.save_document(project, "timeline", {"clips": []}, 0)

    def save(rate):
        try:
            return core.save_document(
                project, "timeline", {"clips": [], "sample_rate": rate}, 1
            )
        except ValueError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, [24000, 48000]))
    assert sum(isinstance(result, dict) for result in results) == 1
    assert "document_revision_conflict" in results
    assert len(core.document_revisions(project, "timeline")["items"]) == 2


def test_revision_api_uses_authenticated_scoped_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    app = create_app(tmp_path, "r" * 64)
    core = app.state.core
    project = core.create_project("API recovery")["id"]
    core.save_document(project, "timeline", {"clips": []}, 0)
    prefix = f"/v1/projects/{project}/documents/timeline"
    with TestClient(app) as client:
        assert client.post(prefix + "/history", json={}).status_code == 401
        headers = {"Authorization": "Bearer " + "r" * 64}
        response = client.post(prefix + "/history", json={}, headers=headers)
        assert (
            response.status_code == 200 and response.json()["items"][0]["revision"] == 1
        )
        assert "content" not in response.json()["items"][0]
        response = client.post(
            prefix + "/restore",
            json={"source_revision": 1, "expected_revision": 0},
            headers=headers,
        )
        assert response.status_code == 409
        response = client.post(
            prefix + "/restore",
            json={"source_revision": 1, "expected_revision": 1},
            headers=headers,
        )
        assert response.status_code == 200 and response.json()["revision"] == 2
        assert (
            client.get("/v1/diagnostics", headers=headers).json()["database_schema"]
            == 11
        )
