import hashlib
import io
from typing import ClassVar
from unittest.mock import patch

import pytest
from nexus_runtime.database import Database
from nexus_runtime.models import ModelManager

DATA = b"model weights for test only"


def manager(tmp_path):
    return ModelManager(
        Database(tmp_path),
        [
            {
                "id": "test",
                "files": [
                    {
                        "name": "model.bin",
                        "url": "https://example.com/model.bin",
                        "size": len(DATA),
                        "sha256": hashlib.sha256(DATA).hexdigest(),
                    }
                ],
            }
        ],
    )


class Response(io.BytesIO):
    status = 200
    headers: ClassVar[dict] = {}


def test_download_verify_and_uninstall(tmp_path):
    m = manager(tmp_path)
    with patch("urllib.request.urlopen", return_value=Response(DATA)):
        m.action("test", "install")
        m.thread.join(5)
    assert m.list()[0]["state"] == "installed"
    assert (m.directory("test") / "model.bin").read_bytes() == DATA
    m.action("test", "verify")
    m.thread.join(5)
    assert m.list()[0]["state"] == "installed"
    m.action("test", "uninstall")
    assert m.list()[0]["state"] == "available"
    assert not (m.root / "test").exists()


def test_corrupt_download_cannot_be_used(tmp_path):
    m = manager(tmp_path)
    with patch("urllib.request.urlopen", return_value=Response(b"x" * len(DATA))):
        m.action("test", "install")
        m.thread.join(5)
    assert m.list()[0]["error"] == "model_checksum_mismatch"
    with pytest.raises(ValueError, match="model_not_installed"):
        m.directory("test")


def test_resume_handles_server_ignoring_range(tmp_path):
    m = manager(tmp_path)
    p = m.root / "test"
    p.mkdir()
    (p / "model.bin.part").write_bytes(DATA[:5])
    with patch("urllib.request.urlopen", return_value=Response(DATA)):
        m.action("test", "resume")
        m.thread.join(5)
    assert (m.directory("test") / "model.bin").read_bytes() == DATA


def test_restart_recovers_download_as_paused(tmp_path):
    m = manager(tmp_path)
    m.state("test", "downloading")
    assert manager(tmp_path).list()[0]["state"] == "paused"


def test_unknown_model_and_action_rejected(tmp_path):
    m = manager(tmp_path)
    with pytest.raises(ValueError):
        m.action("../escape", "install")
    with pytest.raises(ValueError):
        m.action("test", "execute")


def test_resume_promotes_complete_partial_without_network(tmp_path):
    m = manager(tmp_path)
    folder = m.root / "test"
    folder.mkdir()
    (folder / "model.bin.part").write_bytes(DATA)
    with patch("urllib.request.urlopen") as network:
        m.action("test", "resume")
        m.thread.join(5)
        network.assert_not_called()
    assert m.list()[0]["state"] == "installed"
    assert m.list()[0]["downloaded"] == len(DATA)


def test_failed_uninstall_preserves_installed_state(tmp_path):
    m = manager(tmp_path)
    (m.root / "test").mkdir()
    m.state("test", "installed")
    with (
        patch("shutil.rmtree", side_effect=PermissionError),
        pytest.raises(PermissionError),
    ):
        m.action("test", "uninstall")
    assert m.list()[0]["state"] == "installed"
