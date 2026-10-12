import json

from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.core import Core


def test_job_status_is_authenticated_bounded_and_rejects_trashed_project(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Preview")
    job = core.create_tts_job(project["id"], {"text": "private sample"})
    with core.db.connect() as db:
        db.execute(
            "UPDATE jobs SET state='completed',result=? WHERE id=?",
            (
                json.dumps(
                    {
                        "asset_id": "asset",
                        "text": "private transcript",
                        "words": [1, 2, 3],
                    }
                ),
                job["id"],
            ),
        )
    with TestClient(create_app(tmp_path, "v" * 64)) as client:
        path = f"/v1/jobs/{job['id']}/status"
        assert client.get(path).status_code == 401
        response = client.get(path, headers={"Authorization": "Bearer " + "v" * 64})
        assert response.status_code == 200
        assert response.json() == {
            "id": job["id"],
            "state": "completed",
            "error": None,
            "asset_id": "asset",
        }
        core.trash_project(project["id"])
        assert (
            client.get(
                path, headers={"Authorization": "Bearer " + "v" * 64}
            ).status_code
            == 404
        )
