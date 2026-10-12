import json

import pytest
from nexus_runtime.backups import create, restore
from nexus_runtime.core import Core
from nexus_runtime.jobs import JobRunner
from test_workflow import wav


def session(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Safety")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav", seconds=1))
    job = core.create_job(asset["id"])
    identifier = core.save_transcript(
        job,
        {
            "language": "en",
            "segments": [
                {
                    "start": 0,
                    "end": 0.4,
                    "text": "First",
                    "words": [{"start": 0, "end": 0.4, "text": "First"}],
                },
                {
                    "start": 0.4,
                    "end": 0.9,
                    "text": "Second",
                    "words": [{"start": 0.4, "end": 0.9, "text": "Second"}],
                },
            ],
        },
    )
    return core, project, asset, job, identifier


@pytest.mark.parametrize(
    "segments",
    [
        [{"start": 0.7, "end": 0.2, "text": "reversed"}],
        [{"start": 0, "end": 0, "text": "empty"}],
        [{"start": -1, "end": 0.2, "text": "negative"}],
        [{"start": 0, "end": float("nan"), "text": "nan"}],
        [{"start": 0, "end": 2, "text": "outside asset"}],
        [
            {"start": 0.5, "end": 0.7, "text": "later"},
            {"start": 0, "end": 0.2, "text": "earlier"},
        ],
    ],
)
def test_invalid_edit_preserves_content_and_revision(tmp_path, segments):
    core, _, _, _, identifier = session(tmp_path)
    before = core.transcripts()
    with pytest.raises(ValueError, match="invalid_transcript"):
        core.edit_transcript(identifier, 1, segments)
    assert core.transcripts() == before


def test_edit_preserves_unchanged_words_and_invalidates_changed_alignment(tmp_path):
    core, _, _, _, identifier = session(tmp_path)
    original = core.transcripts()[0]["segments"]
    changed = [dict(s) for s in original]
    changed[0]["text"] = "Edited"
    changed[1]["words"] = [{"text": "untrusted client timing"}]
    saved = core.edit_transcript(identifier, 1, changed)
    assert saved["segments"][0]["words"] == []
    assert saved["segments"][0]["word_timestamps_valid"] is False
    assert saved["segments"][1]["words"] == original[1]["words"]
    with pytest.raises(ValueError, match="revision_conflict"):
        core.edit_transcript(identifier, 1, original)
    assert core.transcripts()[0] == saved


@pytest.mark.parametrize(
    "kind,content",
    [
        ("timeline", {"clips": "wrong"}),
        ("timeline", {"clips": [None]}),
        ("audiobook", {"chapters": [{"title": "a", "text": None}]}),
        ("dubbing", {"transcriptId": 42}),
        ("audiobook", {"gap": float("inf")}),
    ],
)
def test_malformed_editor_document_is_not_persisted(tmp_path, kind, content):
    core, project, *_ = session(tmp_path)
    with pytest.raises(ValueError):
        core.save_document(project["id"], kind, content, 0)
    assert core.document(project["id"], kind)["revision"] == 0


def test_cross_project_document_references_rejected(tmp_path):
    core, _, asset, _, transcript = session(tmp_path)
    other = core.create_project("Other")
    with pytest.raises(ValueError, match="asset_project_mismatch"):
        core.save_document(
            other["id"], "timeline", {"clips": [{"asset_id": asset["id"]}]}, 0
        )
    with pytest.raises(ValueError, match="transcript_project_mismatch"):
        core.save_document(other["id"], "dubbing", {"transcriptId": transcript}, 0)


def test_generated_outputs_roll_back_on_worker_failure(tmp_path, monkeypatch):
    core, project, asset, _, _ = session(tmp_path)
    # Cancel original analyze job so the production task is next.
    for job in core.jobs():
        core.cancel(job["id"])
    job = core.create_tts_job(project["id"], {}, "dubbing")
    before = core.db.rows("SELECT id FROM assets")
    from nexus_runtime import production

    def failure(core, *_):
        core.import_file(project["id"], core.asset_path(asset["id"]))
        raise RuntimeError("PRIVATE transcript or path must not enter logs")

    monkeypatch.setattr(production, "dubbing", failure)
    runner = JobRunner(core)
    assert runner.claim_next() == job["id"]
    runner.execute(job["id"])
    assert core.job(job["id"])["state"] == "failed"
    assert core.db.rows("SELECT id FROM assets") == before
    assert len(list(core.assets.glob("*.wav"))) == 1


def test_generated_outputs_roll_back_on_cancel_after_render(tmp_path, monkeypatch):
    core, project, asset, _, _ = session(tmp_path)
    for job in core.jobs():
        core.cancel(job["id"])
    job = core.create_tts_job(project["id"], {}, "dubbing")
    from nexus_runtime import production

    def cancel_after_output(core, *_):
        output = core.import_file(project["id"], core.asset_path(asset["id"]))
        core.cancel(job["id"])
        return {"asset_id": output["id"]}

    monkeypatch.setattr(production, "dubbing", cancel_after_output)
    runner = JobRunner(core)
    runner.claim_next()
    runner.execute(job["id"])
    assert core.job(job["id"])["state"] == "cancelled"
    assert len(core.db.rows("SELECT id FROM assets")) == 1
    assert len(list(core.assets.glob("*.wav"))) == 1


def test_backup_refuses_corrupt_managed_audio(tmp_path):
    core, project, asset, *_ = session(tmp_path)
    core.asset_path(asset["id"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="backup_checksum_mismatch"):
        create(core, project["id"])
    assert list((core.db.root / "backups").iterdir()) == []


def test_backup_creation_obeys_restore_manifest_limit(tmp_path, monkeypatch):
    core, project, *_ = session(tmp_path)
    from nexus_runtime import backups

    monkeypatch.setattr(backups, "MANIFEST_LIMIT", 10)
    with pytest.raises(ValueError, match="backup_size_limit"):
        create(core, project["id"])
    assert not (core.db.root / "backups").exists()


def test_restore_rejects_invalid_transcript_without_partial_project(tmp_path):
    import zipfile

    core, project, *_ = session(tmp_path)
    backup = create(core, project["id"])
    source = core.db.root / "backups" / (backup["id"] + ".nexus")
    bad = tmp_path / "bad.nexus"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(bad, "w") as target:
        for name in original.namelist():
            data = original.read(name)
            if name == "project.json":
                manifest = json.loads(data)
                manifest["transcripts"][0]["segments"][0]["end"] = -1
                data = json.dumps(manifest).encode()
            target.writestr(name, data)
    with pytest.raises(ValueError, match="invalid_transcript"):
        restore(core, bad)
    assert len(core.projects()) == 1
    assert len(list(core.assets.glob("*.wav"))) == 1


def test_diagnostic_events_do_not_include_exception_message(tmp_path):
    from nexus_runtime.auditlog import configure, job_failed

    configure(tmp_path)
    job_failed("job-id", "dubbing", ValueError("SECRET /home/user/private.wav"))
    log = (tmp_path / "logs" / "runtime.jsonl").read_text()
    assert "SECRET" not in log and "/home/user" not in log
    assert json.loads(log)["exception_type"] == "ValueError"


def test_http_edit_keeps_word_timing_and_rejects_invalid_ranges(tmp_path):
    from fastapi.testclient import TestClient
    from nexus_runtime.api import create_app

    token = "x" * 64
    app = create_app(tmp_path / "http", token)
    core = app.state.core
    project = core.create_project("HTTP edit")
    asset = core.import_file(project["id"], wav(tmp_path / "http.wav", seconds=1))
    job = core.create_job(asset["id"])
    core.cancel(job["id"])
    words = [{"start": 0, "end": 0.4, "text": "Original"}]
    identifier = core.save_transcript(
        job,
        {
            "language": "en",
            "segments": [
                {"start": 0, "end": 0.4, "text": "Original", "words": words},
                {"start": 0.4, "end": 0.9, "text": "Second"},
            ],
        },
    )
    with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
        segments = [
            {"start": 0, "end": 0.4, "text": "Original"},
            {"start": 0.4, "end": 0.9, "text": "Edited"},
        ]
        response = client.put(
            "/v1/transcripts/" + identifier, json={"revision": 1, "segments": segments}
        )
        assert response.status_code == 200
        assert response.json()["segments"][0]["words"] == words
        assert response.json()["segments"][1]["word_timestamps_valid"] is False
        segments[0]["end"] = 0
        invalid = client.put(
            "/v1/transcripts/" + identifier, json={"revision": 2, "segments": segments}
        )
        assert invalid.status_code == 409
        assert core.transcripts()[0]["revision"] == 2


def test_restore_rejects_invalid_editor_reference_and_cleans_copied_files(tmp_path):
    import zipfile

    core, project, *_ = session(tmp_path)
    backup = create(core, project["id"])
    original = core.db.root / "backups" / (backup["id"] + ".nexus")
    bad = tmp_path / "bad-document.nexus"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(bad, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "project.json":
                manifest = json.loads(data)
                manifest["documents"] = [
                    {
                        "kind": "timeline",
                        "content": json.dumps({"clips": [{"asset_id": "missing"}]}),
                    }
                ]
                data = json.dumps(manifest).encode()
            target.writestr(name, data)
    with pytest.raises(ValueError):
        restore(core, bad)
    assert len(core.projects()) == 1
    assert len(list(core.assets.glob("*.wav"))) == 1
