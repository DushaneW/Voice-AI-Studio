import uuid

from nexus_runtime.hygiene import cleanup


def test_cleanup_only_owns_disposable_names(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    disposable = backups / f"{uuid.uuid4()}.nexus"
    disposable.write_bytes(b"temporary export")
    keep = backups / "my-project.nexus"
    keep.write_bytes(b"user file")
    temp = tmp_path / "decode-ab12_cd3"
    temp.mkdir()
    (temp / "decoded.wav").write_bytes(b"partial")
    unrelated = tmp_path / "decode-my-recording"
    unrelated.mkdir()
    cleanup(tmp_path)
    assert not disposable.exists() and not temp.exists()
    assert keep.exists() and unrelated.exists()
