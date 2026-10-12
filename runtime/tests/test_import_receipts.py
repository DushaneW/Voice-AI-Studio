import uuid
import wave
from concurrent.futures import ThreadPoolExecutor

import pytest
from nexus_runtime.core import Core, NotFound


def source(tmp_path, name="input.wav", sample=100):
    path = tmp_path / name
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(sample.to_bytes(2, "little", signed=True) * 24)
    return path


def test_retry_survives_restart_and_keeps_distinct_takes(tmp_path):
    root = tmp_path / "workspace"
    core = Core(root)
    project = core.create_project("Takes")["id"]
    path = source(tmp_path)
    key = str(uuid.uuid4())
    first = core.import_file(project, path, request_id=key)
    restarted = Core(root)
    assert restarted.import_file(project, path, request_id=key)["id"] == first["id"]
    assert (
        restarted.import_file(project, path, request_id=str(uuid.uuid4()))["id"]
        != first["id"]
    )
    assert len(list(core.assets.glob("*.wav"))) == 2
    assert not list(core.assets.glob("*.part"))


def test_concurrent_retries_commit_one_asset(tmp_path):
    core = Core(tmp_path / "workspace")
    project = core.create_project("Concurrent")["id"]
    path, key = source(tmp_path), str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: core.import_file(project, path, request_id=key), range(4)
            )
        )
    assert len({r["id"] for r in results}) == 1
    assert len(core.db.rows("SELECT * FROM import_receipts")) == 1
    assert len(list(core.assets.glob("*.wav"))) == 1
    assert not list(core.assets.glob("*.part"))


def test_conflict_and_trash_never_overwrite_or_resurrect(tmp_path):
    core = Core(tmp_path / "workspace")
    project = core.create_project("Conflict")["id"]
    path, key = source(tmp_path), str(uuid.uuid4())
    asset = core.import_file(project, path, request_id=key)
    original = core.asset_path(asset["id"]).read_bytes()
    with pytest.raises(ValueError, match="import_request_conflict"):
        core.import_file(project, source(tmp_path, "other.wav", 200), request_id=key)
    assert core.asset_path(asset["id"]).read_bytes() == original
    core.trash_asset(asset["id"])
    with pytest.raises(NotFound, match="asset_in_trash"):
        core.import_file(project, path, request_id=key)
    assert len(list(core.assets.glob("*.wav"))) == 1


def test_migration_from_eight_preserves_assets(tmp_path):
    core = Core(tmp_path / "workspace")
    project = core.create_project("Existing")["id"]
    asset = core.import_file(project, source(tmp_path))
    with core.db.connect() as db:
        db.execute("DROP TABLE import_receipts")
        for trigger in ["job_event_insert", "job_event_update", "job_notification"]:
            db.execute(f"DROP TRIGGER {trigger}")
        db.execute("DROP TABLE notifications")
        db.execute("DROP TABLE job_events")
        db.execute("DROP INDEX IF EXISTS jobs_active_model")
        db.execute("PRAGMA user_version=8")
    migrated = Core(core.db.root)
    assert migrated.asset(asset["id"])["sha256"] == asset["sha256"]
    with migrated.db.connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 11
    assert Core(core.db.root).asset(asset["id"])["id"] == asset["id"]


def test_response_failure_after_commit_preserves_file_for_retry(tmp_path, monkeypatch):
    core = Core(tmp_path / "workspace")
    project = core.create_project("Lost response")["id"]
    path, key = source(tmp_path), str(uuid.uuid4())
    original = core.asset

    def unavailable(_):
        raise OSError("response interrupted")

    monkeypatch.setattr(core, "asset", unavailable)
    with pytest.raises(OSError):
        core.import_file(project, path, request_id=key)
    monkeypatch.setattr(core, "asset", original)
    result = core.import_file(project, path, request_id=key)
    assert core.asset_path(result["id"]).read_bytes() == path.read_bytes()
    assert len(list(core.assets.glob("*.wav"))) == 1
