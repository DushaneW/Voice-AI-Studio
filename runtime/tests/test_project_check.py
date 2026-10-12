import pytest
from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.jobs import JobRunner
from nexus_runtime.project_check import execute
from test_project_copy import setup


def test_real_validation_and_corruption_are_read_only(tmp_path):
    core, project, asset, _, _ = setup(tmp_path)
    core.save_transcript(
        {"id": None, "project_id": project, "asset_id": asset["id"]},
        {"language": "en", "segments": [{"start": 0, "end": 0.1, "text": "hello"}]},
    )
    progress = []
    result = execute(core, project, progress.append, lambda: False)
    assert result["issue_count"] == 0 and progress[-1] == 1
    assert (
        result["checked_assets"]
        == result["checked_documents"]
        == result["checked_transcripts"]
        == 1
    )
    path = core.asset_path(asset["id"])
    content = bytearray(path.read_bytes())
    content[-1] ^= 1
    path.write_bytes(content)
    result = execute(core, project, lambda _: None, lambda: False)
    assert any(i["code"] == "asset_checksum_mismatch" for i in result["issues"])
    assert path.read_bytes() == content
    assert core.document(project, "timeline")["revision"] == 1


def test_missing_media_and_invalid_document_are_reported(tmp_path):
    core, project, asset, _, _ = setup(tmp_path)
    core.asset_path(asset["id"]).unlink()
    with core.db.connect() as db:
        db.execute("UPDATE documents SET content='[]' WHERE project_id=?", (project,))
    result = execute(core, project, lambda _: None, lambda: False)
    assert {i["code"] for i in result["issues"]} == {
        "asset_missing",
        "document_invalid",
    }


def test_validation_cancellation(tmp_path):
    core, project, _, _, _ = setup(tmp_path)
    with pytest.raises(InterruptedError):
        execute(core, project, lambda _: None, lambda: True)


def test_authenticated_endpoints_queue_and_persist(tmp_path):
    app = create_app(tmp_path / "api", "t" * 64)
    core = app.state.core
    project = core.create_project("API")["id"]
    client = TestClient(app)  # Worker is intentionally driven synchronously.
    prefix = f"/v1/projects/{project}"
    assert client.post(prefix + "/validate").status_code == 401
    client.headers["Authorization"] = "Bearer " + "t" * 64
    response = client.post(prefix + "/validate")
    assert response.status_code == 201
    job = response.json()
    runner = JobRunner(core)
    runner.claim_next(job_id=job["id"])
    runner.execute(job["id"])
    assert core.job(job["id"])["result"]["issue_count"] == 0
    import uuid

    data = {"request_id": str(uuid.uuid4()), "name": "API copy"}
    first = client.post(prefix + "/duplicate", json=data)
    second = client.post(prefix + "/duplicate", json=data)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
