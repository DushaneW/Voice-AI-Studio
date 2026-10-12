from nexus_runtime.core import Core
from nexus_runtime.search import search
from test_workflow import wav


def test_literal_unicode_search_excludes_trash_and_limits_results(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Wrocław 100%")
    for i in range(22):
        core.create_project(f"Match {i}")
    assert len(search(core, "Match")["groups"]["projects"]["items"]) == 20
    assert search(core, "Match")["groups"]["projects"]["more"]
    assert (
        search(core, "WROCŁAW")["groups"]["projects"]["items"][0]["id"] == project["id"]
    )
    assert len(search(core, "0%")["groups"]["projects"]["items"]) == 1
    asset = core.import_file(project["id"], wav(tmp_path / "Match.wav"))
    job = core.create_job(asset["id"], "transcribe")
    transcript = core.save_transcript(
        job,
        {
            "language": "pl",
            "segments": [{"start": 0, "end": 0.1, "text": "Wrocław transcript"}],
        },
    )
    hit = search(core, "WROCŁAW")["groups"]["transcripts"]["items"][0]
    assert hit["id"] == transcript and hit["segment"] == 0
    core.cancel(job["id"])
    core.trash_asset(asset["id"])
    assert not search(core, "Wrocław")["groups"]["transcripts"]["items"]
    assert not search(core, "Match.wav")["groups"]["assets"]["items"]
    core.trash_project(project["id"])
    assert not search(core, "Wrocław")["groups"]["projects"]["items"]


def test_search_api_requires_auth_and_validates_query(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    with TestClient(create_app(tmp_path, "q" * 64)) as client:
        assert client.post("/v1/search", json={"query": "hello"}).status_code == 401
        headers = {"Authorization": "Bearer " + "q" * 64}
        assert (
            client.post("/v1/search", json={"query": "a"}, headers=headers).status_code
            == 422
        )
        assert (
            client.post(
                "/v1/search", json={"query": "hello"}, headers=headers
            ).status_code
            == 200
        )
