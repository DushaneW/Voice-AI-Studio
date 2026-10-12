import json
import zipfile

import pytest
from nexus_runtime.backups import create, restore
from nexus_runtime.core import Core
from test_workflow import wav


def test_roundtrip_audio_documents_and_transcript(tmp_path):
    core = Core(tmp_path / "data")
    p = core.create_project("Portable")
    source = tmp_path / "sample.wav"
    wav(source)
    a = core.import_file(p["id"], source)
    core.save_document(
        p["id"], "timeline", {"clips": [{"asset_id": a["id"], "offset": 0}]}, 0
    )
    job = core.create_job(a["id"])
    core.save_transcript(
        job,
        {"language": "en", "segments": [{"start": 0, "end": 0.1, "text": "Example"}]},
    )
    original = core.transcripts()[0]
    core.save_document(p["id"], "dubbing", {"transcriptId": original["id"]}, 0)
    backup = create(core, p["id"])
    restored = restore(core, core.db.root / "backups" / (backup["id"] + ".nexus"))
    assert restored["id"] != p["id"]
    assets = core.db.rows("SELECT * FROM assets WHERE project_id=?", (restored["id"],))
    assert assets[0]["sha256"] == a["sha256"]
    assert (
        core.document(restored["id"], "timeline")["content"]["clips"][0]["asset_id"]
        == assets[0]["id"]
    )
    transcript = next(
        t for t in core.transcripts() if t["project_id"] == restored["id"]
    )
    assert transcript["id"] != original["id"]
    assert (
        core.document(restored["id"], "dubbing")["content"]["transcriptId"]
        == transcript["id"]
    )


def test_path_traversal_and_invalid_zip_rejected(tmp_path):
    core = Core(tmp_path / "data")
    source = tmp_path / "bad.nexus"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr(
            "project.json",
            json.dumps({"version": 1, "project": {"name": "bad"}, "assets": []}),
        )
        z.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="invalid_backup"):
        restore(core, source)
    assert not core.projects()
    source.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="invalid_backup"):
        restore(core, source)


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        None,
        {"version": 1, "project": {"name": "bad"}, "assets": "wrong"},
        {
            "version": 1,
            "project": {"name": "bad"},
            "documents": [{"kind": "timeline", "content": "[]"}],
        },
    ],
)
def test_invalid_manifest_shapes_leave_workspace_unchanged(tmp_path, manifest):
    core = Core(tmp_path / "data")
    source = tmp_path / "invalid.nexus"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("project.json", json.dumps(manifest))
    with pytest.raises(ValueError, match="invalid_backup"):
        restore(core, source)
    assert core.projects() == []
    assert list(core.assets.iterdir()) == []


def test_backup_preserves_asset_trash_without_resurrecting_media(tmp_path):
    from test_workflow import wav

    core = Core(tmp_path / "data")
    project = core.create_project("Trash snapshot")
    asset = core.import_file(project["id"], wav(tmp_path / "tone.wav"))
    core.trash_asset(asset["id"])
    backup = create(core, project["id"])
    restored = restore(core, core.db.root / "backups" / (backup["id"] + ".nexus"))
    assert core.active_assets(restored["id"]) == []
    stored = core.db.rows("SELECT * FROM assets WHERE project_id=?", (restored["id"],))
    assert len(stored) == 1
    assert stored[0]["sha256"] == asset["sha256"]
    assert core.db.rows(
        "SELECT * FROM asset_trash WHERE asset_id=?", (stored[0]["id"],)
    )
    core.restore_trash("asset", stored[0]["id"])
    assert core.asset_path(stored[0]["id"]).exists()
