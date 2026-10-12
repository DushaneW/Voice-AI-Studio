import json

import pytest
from fastapi.testclient import TestClient
from nexus_runtime import waveforms
from nexus_runtime.api import create_app
from nexus_runtime.core import Core
from nexus_runtime.media import checksum
from test_import_receipts import source


def test_cache_reuses_analysis_and_repairs_corruption(tmp_path, monkeypatch):
    path = source(tmp_path)
    digest = checksum(path)
    first = waveforms.cached_analysis(
        tmp_path, path, digest, lambda _: None, lambda: False
    )

    def forbidden(*_):
        raise AssertionError("audio reread on cache hit")

    original = waveforms.analyze
    monkeypatch.setattr(waveforms, "analyze", forbidden)
    assert (
        waveforms.cached_analysis(tmp_path, path, digest, lambda _: None, lambda: False)
        == first
    )
    cached = next((tmp_path / "cache" / "waveforms").glob("*.json"))
    cached.write_text('{"result":{}}')
    assert waveforms.read(tmp_path, digest) is None
    monkeypatch.setattr(waveforms, "analyze", original)
    assert (
        waveforms.cached_analysis(tmp_path, path, digest, lambda _: None, lambda: False)
        == first
    )
    payload = json.loads(cached.read_text())
    payload["result"]["peaks"] = [float("nan")]
    cached.write_text(json.dumps(payload))
    assert waveforms.read(tmp_path, digest) is None


def test_cache_failure_and_cancellation_do_not_publish_partial_results(
    tmp_path, monkeypatch
):
    path = source(tmp_path)
    digest = checksum(path)
    with pytest.raises(InterruptedError):
        waveforms.cached_analysis(tmp_path, path, digest, lambda _: None, lambda: True)
    assert waveforms.read(tmp_path, digest) is None
    (tmp_path / "cache").write_text("blocked")
    result = waveforms.cached_analysis(
        tmp_path, path, digest, lambda _: None, lambda: False
    )
    assert result["frames"] == 24
    assert waveforms.read(tmp_path, digest) is None


def test_api_cache_survives_jobs_archive_and_rejects_trash(tmp_path):
    core = Core(tmp_path / "workspace")
    project = core.create_project("Waveforms")["id"]
    asset = core.import_file(project, source(tmp_path))
    waveforms.cached_analysis(
        core.db.root,
        core.asset_path(asset["id"]),
        asset["sha256"],
        lambda _: None,
        lambda: False,
    )
    headers = {"Authorization": "Bearer " + "w" * 64}
    with TestClient(create_app(core.db.root, "w" * 64)) as client:
        url = f"/v1/assets/{asset['id']}/waveform"
        assert client.get(url).status_code == 401
        assert client.get(url, headers=headers).json()["analysis"]["frames"] == 24
        assert not core.jobs()
        core.trash_asset(asset["id"])
        assert client.get(url, headers=headers).status_code == 404


def test_disabled_cache_and_quota_preserve_source(tmp_path):
    path = source(tmp_path)
    digest = checksum(path)
    result = waveforms.cached_analysis(
        tmp_path, path, digest, lambda _: None, lambda: False, cache_enabled=False
    )
    assert result["frames"] == 24 and not (tmp_path / "cache").exists()
    original = path.read_bytes()
    waveforms.cached_analysis(
        tmp_path, path, digest, lambda _: None, lambda: False, max_bytes=1
    )
    assert waveforms.read(tmp_path, digest) is None and path.read_bytes() == original


def test_cache_symlink_parent_never_writes_outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "workspace"
    root.mkdir()
    try:
        (root / "cache").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    path = source(tmp_path)
    digest = checksum(path)
    waveforms.cached_analysis(root, path, digest, lambda _: None, lambda: False)
    assert waveforms.read(root, digest) is None and list(outside.iterdir()) == []


def test_quota_only_removes_generated_files(tmp_path):
    folder = tmp_path / "cache" / "waveforms"
    folder.mkdir(parents=True)
    generated = folder / ("v1-" + "a" * 64 + ".json")
    generated.write_bytes(b"0123456789")
    keep = folder / "user.json"
    keep.write_bytes(b"preserve")
    waveforms.prune(tmp_path, 1)
    assert not generated.exists() and keep.read_bytes() == b"preserve"
