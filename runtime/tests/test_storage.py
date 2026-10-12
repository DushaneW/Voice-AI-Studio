import pytest
from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.core import Core
from nexus_runtime.storage import clear_waveforms, inventory, measure
from test_workflow import wav


def test_inventory_and_confirmed_clear_preserve_user_data(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Storage")["id"]
    asset = core.import_file(project, wav(tmp_path / "input.wav"))
    core.trash_asset(asset["id"])
    folder = core.db.root / "cache" / "waveforms"
    folder.mkdir(parents=True)
    generated = folder / ("v1-" + "a" * 64 + ".json")
    generated.write_text("{}")
    personal = folder / "notes.json"
    personal.write_text("keep")
    model = core.db.root / "models"
    model.mkdir(exist_ok=True)
    (model / "weights.bin").write_bytes(b"model")
    report = inventory(core)
    assert report["trash_audio_bytes"] == asset["size"]
    assert report["categories"]["assets"]["bytes"] == asset["size"]
    assert report["categories"]["models"]["bytes"] == 5
    with TestClient(create_app(core.db.root, "c" * 64)) as client:
        headers = {"Authorization": "Bearer " + "c" * 64}
        url = "/v1/storage/waveforms/clear"
        assert client.post(url, json={"confirmed": True}).status_code == 401
        assert (
            client.post(url, json={"confirmed": False}, headers=headers).status_code
            == 422
        )
        assert generated.exists()
        response = client.post(url, json={"confirmed": True}, headers=headers)
        assert response.status_code == 200 and response.json()["removed"] == 1
        assert client.get("/v1/storage", headers=headers).status_code == 200
    assert personal.read_text() == "keep"
    assert (model / "weights.bin").read_bytes() == b"model"
    assert (core.assets / asset["path"]).exists()


def test_inventory_is_bounded_and_cache_symlinks_are_not_followed(
    tmp_path, monkeypatch
):
    from nexus_runtime import storage

    root = tmp_path / "workspace"
    root.mkdir()
    for name in ("a", "b", "c"):
        (root / name).write_bytes(b"123")
    monkeypatch.setattr(storage, "LIMIT", 1)
    result = measure(root)
    assert result["complete"] is False and result["bytes"] == 3
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "important").write_text("keep")
    try:
        (root / "cache").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink permission unavailable")
    with pytest.raises(ValueError, match="unsafe_cache_path"):
        clear_waveforms(root)
    assert (outside / "important").read_text() == "keep"
