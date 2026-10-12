import pytest
from nexus_runtime.core import Core
from test_workflow import wav


def test_transcription_job_kind_and_revision_conflicts(tmp_path):
    core = Core(tmp_path / "data")
    p = core.create_project("Transcript")
    source = tmp_path / "sample.wav"
    wav(source, seconds=1)
    a = core.import_file(p["id"], source)
    job = core.create_job(a["id"], "transcribe", {"model_id": "whisper-tiny"})
    assert job["kind"] == "transcribe"
    identifier = core.save_transcript(
        job, {"language": "en", "segments": [{"start": 0, "end": 1, "text": "First"}]}
    )
    updated = core.edit_transcript(
        identifier, 1, [{"start": 0, "end": 1, "text": "Edited"}]
    )
    assert updated["revision"] == 2
    with pytest.raises(ValueError, match="revision_conflict"):
        core.edit_transcript(identifier, 1, [])
    assert Core(tmp_path / "data").transcripts()[0]["segments"][0]["text"] == "Edited"


@pytest.mark.parametrize("kind", ["project", "asset"])
def test_edit_of_trashed_transcript_does_not_mutate_database(tmp_path, kind):
    core = Core(tmp_path / "data")
    project = core.create_project("Protected")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    segments = [{"start": 0, "end": 1, "text": "Original"}]
    identifier = core.save_transcript(job, {"language": "en", "segments": segments})
    core.cancel(job["id"])
    if kind == "project":
        core.trash_project(project["id"])
    else:
        core.trash_asset(asset["id"])
    before = core.db.rows("SELECT * FROM transcripts WHERE id=?", (identifier,))
    with pytest.raises(ValueError, match="transcript_not_found"):
        core.edit_transcript(identifier, 1, [{"start": 0, "end": 1, "text": "Changed"}])
    assert core.db.rows("SELECT * FROM transcripts WHERE id=?", (identifier,)) == before


def test_transcript_restore_preserves_old_words_and_creates_new_revision(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("History")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    original = [
        {
            "start": 0,
            "end": 1,
            "text": "Original",
            "words": [{"start": 0, "end": 0.5, "text": "Original", "probability": 0.9}],
        }
    ]
    identifier = core.save_transcript(job, {"language": "en", "segments": original})
    core.edit_transcript(identifier, 1, [{"start": 0, "end": 1, "text": "Changed"}])
    restored = core.restore_transcript(identifier, 1, 2)
    assert restored["revision"] == 3
    assert restored["segments"] == original
    assert [x["revision"] for x in core.transcript_revisions(identifier)["items"]] == [
        3,
        2,
        1,
    ]
    with pytest.raises(ValueError, match="transcript_revision_conflict"):
        core.restore_transcript(identifier, 2, 2)
    assert len(core.transcript_revisions(identifier)["items"]) == 3
    assert Core(tmp_path / "data").transcripts()[0]["revision"] == 3


def test_transcript_snapshot_failure_rolls_back_edit(tmp_path):
    import sqlite3

    core = Core(tmp_path / "data")
    project = core.create_project("Atomic")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    identifier = core.save_transcript(
        job,
        {"language": "en", "segments": [{"start": 0, "end": 1, "text": "Original"}]},
    )
    with core.db.connect() as db:
        db.execute(
            "CREATE TRIGGER no_snapshot BEFORE INSERT ON transcript_revisions BEGIN SELECT RAISE(ABORT,'disk_failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="disk_failure"):
        core.edit_transcript(identifier, 1, [{"start": 0, "end": 1, "text": "Changed"}])
    assert core.transcripts()[0]["revision"] == 1
    assert core.transcripts()[0]["segments"][0]["text"] == "Original"


def test_upgrade_v7_snapshots_current_transcript(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Upgrade")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    identifier = core.save_transcript(
        job, {"language": "en", "segments": [{"start": 0, "end": 1, "text": "Before"}]}
    )
    core.edit_transcript(identifier, 1, [{"start": 0, "end": 1, "text": "Current"}])
    with core.db.connect() as db:
        db.execute("DROP TRIGGER transcript_snapshot_insert")
        db.execute("DROP TRIGGER transcript_snapshot_update")
        db.execute("DROP TABLE transcript_revisions")
        db.execute("DROP TABLE import_receipts")
        for trigger in ["job_event_insert", "job_event_update", "job_notification"]:
            db.execute(f"DROP TRIGGER {trigger}")
        db.execute("DROP TABLE notifications")
        db.execute("DROP TABLE job_events")
        db.execute("DROP INDEX IF EXISTS jobs_active_model")
        db.execute("PRAGMA user_version=7")
    upgraded = Core(tmp_path / "data")
    assert [
        r["revision"] for r in upgraded.transcript_revisions(identifier)["items"]
    ] == [2]
    assert upgraded.transcripts()[0]["segments"][0]["text"] == "Current"
    upgraded.edit_transcript(identifier, 2, [{"start": 0, "end": 1, "text": "New"}])
    assert [
        r["revision"] for r in upgraded.transcript_revisions(identifier)["items"]
    ] == [3, 2]


def test_transcript_history_api_keeps_words_in_storage(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    app = create_app(tmp_path / "data", "t" * 64)
    core = app.state.core
    project = core.create_project("API")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    original = [
        {
            "start": 0,
            "end": 1,
            "text": "Text",
            "words": [{"start": 0, "end": 1, "text": "Text"}],
        }
    ]
    identifier = core.save_transcript(job, {"language": "en", "segments": original})
    core.cancel(job["id"])
    headers = {"Authorization": "Bearer " + "t" * 64}
    prefix = f"/v1/transcripts/{identifier}"
    with TestClient(app) as client:
        assert client.post(prefix + "/history", json={}).status_code == 401
        assert (
            client.post(prefix + "/history", json={}, headers=headers).json()["items"][
                0
            ]["revision"]
            == 1
        )
        response = client.post(
            prefix + "/restore",
            json={"source_revision": 1, "expected_revision": 1},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["revision"] == 2
        assert "words" not in response.json()["content"]["segments"][0]
        assert core.transcripts()[0]["segments"] == original


def test_structural_edits_invalidate_alignment_and_persist_history(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Structural editing")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=2))
    job = core.create_job(asset["id"], "transcribe")
    original = [
        {
            "start": 0,
            "end": 2,
            "text": "Hello world",
            "speaker": "Alice",
            "words": [{"start": 0, "end": 1, "text": "Hello"}],
        }
    ]
    identifier = core.save_transcript(job, {"language": "en", "segments": original})
    split = [
        {"start": 0, "end": 0.8, "text": "Hello", "speaker": "Alice"},
        {"start": 0.8, "end": 2, "text": "world", "speaker": "Alice"},
    ]
    edited = core.edit_transcript(identifier, 1, split)
    assert all(
        s["words"] == [] and not s["word_timestamps_valid"] for s in edited["segments"]
    )
    assert Core(core.db.root).transcripts()[0]["segments"] == edited["segments"]
    restored = core.restore_transcript(identifier, 1, 2)
    assert restored["revision"] == 3 and restored["segments"] == original
