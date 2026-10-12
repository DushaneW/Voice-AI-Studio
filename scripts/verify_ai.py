"""Opt-in real CPU smoke test against explicitly prepared, hash-pinned models.

Usage: python scripts/verify_ai.py PATH_TO_TEST_DATA
Requires runtime[ai,test] and model folders beneath PATH_TO_TEST_DATA/models.
Does not download models, use network inference or invent an expected transcript.
"""

import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.media import probe
from nexus_runtime.models import CATALOG

root = Path(sys.argv[1]).resolve()
report = {
    "test": "real CPU speech → transcription → persisted edit",
    "models": {m["id"]: m["revision"] for m in CATALOG},
}
with TestClient(create_app(root, "smoke-test-token-" + "x" * 40)) as client:
    client.headers["Authorization"] = "Bearer " + "smoke-test-token-" + "x" * 40
    for model in CATALOG:
        client.post("/v1/models/" + model["id"] + "/install").raise_for_status()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = next(
                m for m in client.get("/v1/models").json() if m["id"] == model["id"]
            )
            if state["state"] not in {"downloading", "verifying"}:
                break
            time.sleep(0.1)
        assert state["state"] == "installed", state
    project = client.post(
        "/v1/projects", json={"name": "AI integration verification"}
    ).json()
    started = time.monotonic()
    tts = client.post(
        "/v1/tts",
        json={
            "project_id": project["id"],
            "text": "Welcome to Nexus. Your voice, your workspace, entirely local.",
            "voice": "af_heart",
            "language": "en-us",
        },
    )
    tts.raise_for_status()

    def wait(identifier):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = next(
                j for j in client.get("/v1/jobs").json() if j["id"] == identifier
            )
            if job["state"] in {"completed", "failed", "cancelled", "interrupted"}:
                assert job["state"] == "completed", job
                return job
            time.sleep(0.1)
        raise TimeoutError("inference deadline")

    output = wait(tts.json()["id"])
    report["tts_seconds"] = time.monotonic() - started
    asset = output["result"]["asset_id"]
    audio = client.get("/v1/assets/" + asset + "/audio")
    audio.raise_for_status()
    (root / "smoke-speech.wav").write_bytes(audio.content)
    report["audio"] = probe(root / "smoke-speech.wav")
    started = time.monotonic()
    asr = client.post("/v1/transcribe", json={"asset_id": asset, "language": "en"})
    asr.raise_for_status()
    output = wait(asr.json()["id"])
    report["asr_seconds"] = time.monotonic() - started
    transcript = next(
        t
        for t in client.get("/v1/transcripts").json()
        if t["id"] == output["result"]["transcript_id"]
    )
    report["recognized_text"] = " ".join(s["text"] for s in transcript["segments"])
    assert "nexus" in report["recognized_text"].lower(), report
    edited = transcript["segments"]
    edited[0]["text"] = "Welcome to NEXUS. Edited transcript."
    saved = client.put(
        "/v1/transcripts/" + transcript["id"],
        json={"revision": transcript["revision"], "segments": edited},
    )
    saved.raise_for_status()
    assert saved.json()["revision"] == 2
    srt = client.get("/v1/transcripts/" + transcript["id"] + "/export/srt")
    srt.raise_for_status()
    assert "Edited transcript." in srt.json()["text"]
    book = client.post(
        "/v1/audiobook",
        json={
            "project_id": project["id"],
            "voice": "af_heart",
            "chapters": [
                {
                    "title": "Opening",
                    "text": "Chapter one. Welcome to your local studio.",
                },
                {"title": "Next", "text": "Chapter two. The next session starts here."},
            ],
            "gap": 0.25,
        },
    )
    book.raise_for_status()
    book_output = wait(book.json()["id"])
    assert len(book_output["result"]["chapters"]) == 2
    assert (
        book_output["result"]["chapters"][1]["start"]
        >= book_output["result"]["chapters"][0]["end"] + 0.24
    )
    report["audiobook_duration"] = book_output["result"]["duration"]
    dub = client.post(
        "/v1/dubbing",
        json={
            "project_id": project["id"],
            "transcript_id": transcript["id"],
            "voice": "af_heart",
        },
    )
    dub.raise_for_status()
    dub_output = wait(dub.json()["id"])
    report["dubbing_duration"] = dub_output["result"]["duration"]
    report["dubbing_overruns"] = dub_output["result"]["overruns"]
    report["result"] = "passed"
(root / "ai-verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
