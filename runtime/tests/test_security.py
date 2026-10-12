import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from test_models import DATA, Response, manager


def test_download_policy_preserves_local_verify(tmp_path):
    m = manager(tmp_path)
    with patch("urllib.request.urlopen", return_value=Response(DATA)):
        m.action("test", "install")
        m.thread.join(5)
    with m.db.connect() as db:
        db.execute(
            "INSERT INTO settings(key,value) VALUES('model_downloads_allowed','false')"
        )
    with patch(
        "urllib.request.urlopen", side_effect=AssertionError("network forbidden")
    ):
        for action in ("install", "resume", "repair"):
            with pytest.raises(ValueError, match="model_downloads_disabled"):
                m.action("test", action)
        m.action("test", "verify")
        m.thread.join(5)
        assert m.list()[0]["state"] == "installed"


def test_disabling_active_download_pauses_before_publish(tmp_path):
    m = manager(tmp_path)

    class Disable(Response):
        def read(self, size=-1):
            with m.db.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO settings(key,value) VALUES('model_downloads_allowed','false')"
                )
            return super().read(size)

    with patch("urllib.request.urlopen", return_value=Disable(DATA)):
        m.action("test", "install")
        m.thread.join(5)
    assert (
        m.list()[0]["state"] == "paused"
        and not (m.root / "test" / "model.bin").exists()
    )


def test_security_endpoints_auth_privacy_and_permissions(tmp_path):
    token = "secret-canary-" + "x" * 50
    app = create_app(tmp_path, token)
    app.state.core.create_project("PRIVATE_PROJECT_CANARY")
    client = TestClient(app)
    for route in ("/v1/security", "/v1/privacy"):
        assert client.get(route).status_code == 401
        result = client.get(route, headers={"Authorization": "Bearer " + token})
        assert (
            result.status_code == 200
            and token not in result.text
            and "PRIVATE_PROJECT_CANARY" not in result.text
        )
    client.headers["Authorization"] = "Bearer " + token
    privacy = client.get("/v1/privacy").json()
    assert (
        privacy["cloud_providers"] == []
        and privacy["telemetry"] == "not_implemented"
        and not privacy["system_network_monitoring"]
    )
    if os.name == "posix":
        (tmp_path / "assets").chmod(0o755)
        report = client.get("/v1/security").json()
        assert (
            next(e for e in report["workspace"]["entries"] if e["name"] == "assets")[
                "private"
            ]
            is False
        )
    assert (
        client.put(
            "/v1/settings",
            json={
                "language": "en",
                "workspace": "settings",
                "model_downloads_allowed": False,
            },
        ).status_code
        == 200
    )
    assert client.get("/v1/privacy").json()["model_downloads_allowed"] is False
