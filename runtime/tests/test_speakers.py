import pytest
from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.backups import create, restore
from nexus_runtime.core import Core
from nexus_runtime.validation import merge_transcript_edit
from test_workflow import wav


def test_manual_speaker_api_preserves_words_revisions_and_backup(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Speakers")["id"]
    asset = core.import_file(project, wav(tmp_path / "input.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    segment = {
        "start": 0,
        "end": 1,
        "text": "Hello",
        "words": [{"start": 0, "end": 1, "text": "Hello"}],
    }
    identifier = core.save_transcript(job, {"language": "en", "segments": [segment]})
    with TestClient(create_app(core.db.root, "s" * 64)) as client:
        headers = {"Authorization": "Bearer " + "s" * 64}
        response = client.put(
            f"/v1/transcripts/{identifier}",
            headers=headers,
            json={
                "revision": 1,
                "segments": [
                    {"start": 0, "end": 1, "text": "Hello", "speaker": "Alice"}
                ],
            },
        )
        assert response.status_code == 200
        edited = response.json()["segments"][0]
        assert edited["speaker"] == "Alice" and edited["words"] == segment["words"]
        # Older clients that omit the new field must not erase the assignment.
        response = client.put(
            f"/v1/transcripts/{identifier}",
            headers=headers,
            json={"revision": 2, "segments": [{"start": 0, "end": 1, "text": "Hello"}]},
        )
        assert response.json()["segments"][0]["speaker"] == "Alice"
    backup = create(core, project)
    restored = restore(core, core.db.root / "backups" / (backup["id"] + ".nexus"))
    copied = next(t for t in core.transcripts() if t["project_id"] == restored["id"])
    assert copied["segments"][0]["speaker"] == "Alice"
    previous = core.restore_transcript(identifier, 1, 3)
    assert "speaker" not in previous["segments"][0]


def test_unassign_and_text_edit_never_trust_client_word_timing():
    original = [
        {
            "start": 0,
            "end": 1,
            "text": "Hello",
            "speaker": "Alice",
            "words": [{"start": 0, "end": 1, "text": "Hello"}],
        }
    ]
    edited = [
        {
            "start": 0,
            "end": 1,
            "text": "Changed",
            "speaker": "Bob",
            "words": [{"start": -9}],
        }
    ]
    result = merge_transcript_edit(original, edited, 1)
    assert result[0]["speaker"] == "Bob" and result[0]["words"] == []
    cleared = merge_transcript_edit(
        original, [{"start": 0, "end": 1, "text": "Hello", "speaker": None}], 1
    )
    assert "speaker" not in cleared[0] and cleared[0]["words"] == original[0]["words"]
    for name in ["", "x" * 81, " A ", "A\nB", 3]:
        with pytest.raises(ValueError, match="invalid_speaker"):
            merge_transcript_edit(
                original, [{"start": 0, "end": 1, "text": "Hello", "speaker": name}], 1
            )
