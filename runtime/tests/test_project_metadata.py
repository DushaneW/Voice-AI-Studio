import pytest
from nexus_runtime.backups import create, restore
from nexus_runtime.core import Core


def test_metadata_revisions_backup_and_conflict(tmp_path):
    core = Core(tmp_path)
    project = core.create_project("Metadata")["id"]
    metadata = {
        "author": "Author",
        "description": "Notes",
        "language": "pl",
        "tags": [" tag ", "tag"],
    }
    saved = core.save_document(project, "project", metadata, 0)
    assert saved["content"]["tags"] == ["tag"]
    core.save_document(project, "project", {**metadata, "author": "Updated"}, 1)
    with pytest.raises(ValueError, match="revision_conflict"):
        core.save_document(project, "project", metadata, 1)
    core.restore_document(project, "project", 1, 2)
    backup = create(core, project)
    copied = restore(core, core.db.root / "backups" / (backup["id"] + ".nexus"))
    assert (
        Core(tmp_path).document(copied["id"], "project")["content"] == saved["content"]
    )
    assert len(core.document_revisions(project, "project")["items"]) == 3


@pytest.mark.parametrize(
    "content",
    [
        {"author": "x" * 121},
        {"tags": [""]},
        {"tags": ["a"] * 21},
        {"tags": ["bad\nline"]},
        {"unknown": 1},
    ],
)
def test_invalid_metadata_cannot_change_document(tmp_path, content):
    core = Core(tmp_path)
    project = core.create_project("Invalid")["id"]
    with pytest.raises(ValueError, match="invalid_project_metadata"):
        core.save_document(project, "project", content, 0)
    assert core.document(project, "project")["revision"] == 0


def test_settings_persist_and_reject_unbounded_history(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    app = create_app(tmp_path, "a" * 64)
    client = TestClient(app, headers={"Authorization": "Bearer " + "a" * 64})
    project = app.state.core.create_project("Recent")["id"]
    value = {
        "language": "en",
        "workspace": "projects",
        "last_project_id": project,
        "recent_project_ids": [project],
        "autosave_seconds": 15,
    }
    assert client.put("/v1/settings", json=value).status_code == 200
    saved = client.get("/v1/settings").json()
    assert all(saved[k] == v for k, v in value.items())
    assert Core(tmp_path).db.settings()["autosave_seconds"] == 15
    assert (
        client.put("/v1/settings", json={**value, "autosave_seconds": 1}).status_code
        == 422
    )
    assert (
        client.put(
            "/v1/settings", json={**value, "recent_project_ids": [project] * 21}
        ).status_code
        == 422
    )


def test_inference_preferences_survive_restart_and_validate(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    headers = {"Authorization": "Bearer " + "a" * 64}
    client = TestClient(create_app(tmp_path, "a" * 64), headers=headers)
    prefs = {
        "language": "en",
        "workspace": "settings",
        "transcription_model": "whisper-tiny",
        "transcription_language": "pl",
        "transcription_device": "cpu",
        "tts_voice": "af_heart",
        "tts_speed": 1.4,
    }
    assert client.put("/v1/settings", json=prefs).status_code == 200
    reopened = TestClient(create_app(tmp_path, "a" * 64), headers=headers)
    assert all(reopened.get("/v1/settings").json()[k] == v for k, v in prefs.items())
    for invalid in (
        {"tts_speed": 3},
        {"transcription_language": "../../"},
        {"transcription_model": "kokoro-v1"},
        {"transcription_device": "unknown"},
        {"tts_voice": "invalid"},
    ):
        assert client.put("/v1/settings", json={**prefs, **invalid}).status_code in (
            409,
            422,
        )
        assert client.get("/v1/settings").json()["tts_speed"] == 1.4


def test_audio_defaults_persist_and_reject_invalid_capture_options(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    client = TestClient(
        create_app(tmp_path, "a" * 64), headers={"Authorization": "Bearer " + "a" * 64}
    )
    prefs = {
        "language": "en",
        "workspace": "settings",
        "recording_sample_rate": 44100,
        "recording_channels": 2,
        "recording_gain": 0.6,
        "recording_preroll": 2,
        "recording_countdown": 3,
        "playback_volume": 0.4,
        "playback_muted": True,
    }
    assert client.put("/v1/settings", json=prefs).status_code == 200
    assert all(Core(tmp_path).db.settings()[k] == v for k, v in prefs.items())
    for invalid in (
        {"recording_sample_rate": 1},
        {"recording_channels": 3},
        {"recording_gain": 5},
        {"recording_preroll": 10},
        {"recording_countdown": -1},
        {"playback_volume": 2},
    ):
        assert client.put("/v1/settings", json={**prefs, **invalid}).status_code == 422
        assert client.get("/v1/settings").json()["recording_gain"] == 0.6


def test_motion_preference_persists_and_rejects_unknown_values(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    headers = {"Authorization": "Bearer " + "a" * 64}
    client = TestClient(create_app(tmp_path, "a" * 64), headers=headers)
    assert client.get("/v1/settings").json()["motion"] == "system"
    prefs = {"language": "en", "workspace": "settings", "motion": "reduced"}
    assert client.put("/v1/settings", json=prefs).status_code == 200
    reopened = TestClient(create_app(tmp_path, "a" * 64), headers=headers)
    assert reopened.get("/v1/settings").json()["motion"] == "reduced"
    invalid = {**prefs, "motion": "wild"}
    assert client.put("/v1/settings", json=invalid).status_code == 422
