"""Exercise a packaged runtime in a disposable workspace without AI downloads."""

import array
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
import uuid
from pathlib import Path


def verify(binary):
    with tempfile.TemporaryDirectory(prefix="nexus-package-check-") as temporary:
        root = Path(temporary)
        token = secrets.token_hex(32)
        process = subprocess.Popen(
            [str(Path(binary).resolve())],
            env={**os.environ, "NEXUS_DATA_DIR": str(root)},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        base = None
        try:
            process.stdin.write(token + "\n")
            process.stdin.flush()
            lines = queue.Queue()
            threading.Thread(
                target=lambda: lines.put(process.stdout.readline()), daemon=True
            ).start()
            hello = json.loads(lines.get(timeout=30))
            assert hello["api_version"] == "1" and 0 < hello["port"] < 65536
            base = "http://127.0.0.1:" + str(hello["port"])
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

            def request(method, path, data=None, auth=True, origin=False):
                headers = {"Authorization": "Bearer " + token} if auth else {}
                if data is not None:
                    headers["Content-Type"] = "application/json"
                if origin:
                    headers["Origin"] = "https://example.invalid"
                with opener.open(
                    urllib.request.Request(
                        base + path,
                        data=json.dumps(data).encode() if data is not None else None,
                        headers=headers,
                        method=method,
                    ),
                    timeout=10,
                ) as response:
                    payload = response.read()
                    return json.loads(payload) if payload else None

            deadline = time.monotonic() + 15
            while True:
                try:
                    assert request("GET", "/health")["status"] == "ready"
                    break
                except (urllib.error.URLError, ConnectionError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            for auth, origin, expected in [(False, False, 401), (True, True, 403)]:
                try:
                    request("GET", "/health", auth=auth, origin=origin)
                except urllib.error.HTTPError as exc:
                    assert exc.code == expected
                else:
                    raise AssertionError("Authorization guard missing")
            assert len(request("GET", "/v1/models")) >= 2
            project = request("POST", "/v1/projects", {"name": "Packaged regression"})
            source = root / "input.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(array.array("h", [1024] * 2400).tobytes())
            asset = request(
                "POST",
                "/v1/assets/import",
                {"project_id": project["id"], "path": str(source)},
            )
            job = request("POST", "/v1/jobs", {"asset_id": asset["id"]})
            deadline = time.monotonic() + 15
            while True:
                result = next(
                    j for j in request("GET", "/v1/jobs") if j["id"] == job["id"]
                )
                if result["state"] == "completed":
                    break
                assert result["state"] != "failed"
                if time.monotonic() > deadline:
                    raise TimeoutError("packaged job did not finish")
                time.sleep(0.05)
            assert request("POST", "/v1/jobs/archive")["archived"] >= 1
            assert all(j["id"] != job["id"] for j in request("GET", "/v1/jobs"))
            assert any(j["id"] == job["id"] for j in request("GET", "/v1/jobs/archive"))
            assert request("POST", "/v1/jobs/archive/restore")["restored"] >= 1
            assert any(j["id"] == job["id"] for j in request("GET", "/v1/jobs"))
            document_path = "/v1/projects/" + project["id"] + "/documents/timeline"
            clips = [{"asset_id": asset["id"], "track_id": "main", "offset": 0,
                      "trim_start": 0, "trim_end": .1, "gain": 1, "fade_in": 0, "fade_out": 0}]
            content = {"clips": clips, "tracks": [{"id": "main", "name": "Voice", "volume": .5}], "sample_rate": 48000, "channels": 2}
            saved = request("PUT", document_path, {"revision": 0, "content": content})
            assert saved["revision"] == 1
            request("PUT", document_path, {"revision": 1, "content": {**content, "channels": 1}})
            recovered = request("POST", document_path + "/restore", {"source_revision": 1, "expected_revision": 2})
            assert recovered["revision"] == 3 and recovered["content"]["channels"] == 2
            assert len(request("POST", document_path + "/history", {})["items"]) == 3
            rendered = request("POST", "/v1/timeline/render", {"project_id": project["id"], **content})
            deadline = time.monotonic() + 15
            while True:
                row = next(j for j in request("GET", "/v1/jobs") if j["id"] == rendered["id"])
                if row["state"] == "completed":
                    assert row["result"]["channels"] == 2 and row["result"]["sample_rate"] == 48000
                    break
                assert row["state"] != "failed", row.get("error")
                if time.monotonic() > deadline:
                    raise TimeoutError("packaged render did not finish")
                time.sleep(.05)
            request("DELETE", "/v1/projects/" + project["id"])
            assert not any(p["id"] == project["id"] for p in request("GET", "/v1/projects"))
            assert request("POST", "/v1/trash/search", {})["items"][0]["id"] == project["id"]
            request("POST", "/v1/trash/project/" + project["id"] + "/restore")
            assert request("GET", document_path)["revision"] == 3
            backup = request("POST", "/v1/projects/" + project["id"] + "/backup")
            restored = request(
                "POST",
                "/v1/backups/restore",
                {"path": str(root / "backups" / (backup["id"] + ".nexus"))},
            )
            assert restored["id"] != project["id"]
            def wait_job(queued):
                deadline = time.monotonic() + 20
                while True:
                    row = next(j for j in request("GET", "/v1/jobs") if j["id"] == queued["id"])
                    if row["state"] == "completed":
                        return row
                    assert row["state"] not in {"failed", "cancelled", "interrupted"}, row
                    if time.monotonic() > deadline:
                        raise TimeoutError("foundation job did not finish")
                    time.sleep(.05)

            metadata_path = "/v1/projects/" + project["id"] + "/documents/project"
            request("PUT", metadata_path, {"revision": 0, "content": {"author": "Smoke", "tags": ["regression"]}})
            preferences = request("GET", "/v1/settings")
            request("PUT", "/v1/settings", {**preferences, "model_downloads_allowed": False, "tts_speed": 1.4, "transcription_language": "pl"})
            assert request("GET", "/v1/privacy")["model_downloads_allowed"] is False
            try:
                request("POST", "/v1/models/whisper-tiny/install")
            except urllib.error.HTTPError as error:
                assert error.code == 409
                assert json.loads(error.read())["detail"] == "model_downloads_disabled"
            else:
                raise AssertionError("Model job ignored persisted network policy")
            assert request("GET", "/v1/diagnostics")["database_schema"] == 11
            assert request("GET", "/v1/security")["api"]["authentication"] == "bearer"
            host = request("GET", "/v1/diagnostics")["host"]
            assert host["architecture"] and (host["process_rss"] is None or host["process_rss"] > 0)
            checked = wait_job(request("POST", "/v1/projects/" + project["id"] + "/validate"))
            assert checked["result"]["issue_count"] == 0
            plan = wait_job(request("POST", "/v1/projects/" + project["id"] + "/repair-plan"))
            assert plan["result"]["actions"] == [] and plan["result"]["unresolved"] == []
            duplicate_request = {"request_id": str(uuid.uuid4()), "name": "Independent copy"}
            copy_path = "/v1/projects/" + project["id"] + "/duplicate"
            copied = request("POST", copy_path, duplicate_request)
            assert request("POST", copy_path, duplicate_request)["id"] == copied["id"]
            wait_job(copied)
            event_log = request("POST", "/v1/jobs/" + copied["id"] + "/events", {})
            assert {event["state"] for event in event_log["items"]} >= {"queued", "running", "completed"}
            notice = next(n for n in request("POST", "/v1/notifications/search", {})["items"] if n["job_id"] == copied["id"])
            request("POST", "/v1/notifications/" + str(notice["id"]) + "/read")
            assert not any(n["id"] == notice["id"] for n in request("POST", "/v1/notifications/search", {"unread_only": True})["items"])
            request("POST", "/shutdown")
            process.wait(timeout=15)
            assert process.returncode == 0
            # A new process must acquire the same workspace after normal shutdown,
            # then terminate when its parent pipe closes without an HTTP request.
            second = subprocess.Popen(
                [str(Path(binary).resolve())],
                env={**os.environ, "NEXUS_DATA_DIR": str(root)},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True,
            )
            try:
                second.stdin.write(token + "\n")
                second.stdin.flush()
                lines = queue.Queue()
                threading.Thread(target=lambda: lines.put(second.stdout.readline()), daemon=True).start()
                hello = json.loads(lines.get(timeout=30))
                base = "http://127.0.0.1:" + str(hello["port"])
                deadline = time.monotonic() + 10
                while True:
                    try:
                        request("GET", "/health")
                        assert request("GET", "/v1/settings")["tts_speed"] == 1.4
                        assert request("GET", metadata_path)["content"]["author"] == "Smoke"
                        break
                    except (OSError, urllib.error.URLError):
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.05)
                second.stdin.close()
                assert second.wait(timeout=15) == 0
            finally:
                if second.poll() is None:
                    second.kill()
                    second.wait()
                if not second.stdin.closed:
                    second.stdin.close()
                second.stdout.close()
            return {
                "ok": True,
                "checks": [
                    "handshake",
                    "health",
                    "auth_401",
                    "origin_403",
                    "model_catalog",
                    "project",
                    "import",
                    "analysis",
                    "job_archive_restore",
                    "backup_restore",
                    "document_revision_restore",
                    "multitrack_stereo_render",
                    "project_trash_restore",
                    "project_validation_repair_plan",
                    "project_duplicate_idempotence",
                    "job_events_notification_ack",
                    "privacy_security_hardware",
                    "persistent_model_job_network_policy",
                    "settings_metadata_restart_persistence",
                    "shutdown",
                    "parent_eof_shutdown_and_lock_reuse",
                ],
                "ai_inference": False,
            }
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if not process.stdin.closed:
                process.stdin.close()
            process.stdout.close()


if __name__ == "__main__":
    print(json.dumps(verify(sys.argv[1]), indent=2))
