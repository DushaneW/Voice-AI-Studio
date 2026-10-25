import uuid

import pytest
from fastapi.testclient import TestClient
from nexus_runtime.api import create_app
from nexus_runtime.core import Core
from nexus_runtime.subtitle_import import parse
from test_workflow import wav

SRT = "1\r\n00:00:00,000 --> 00:00:00,500\r\nHello\r\nworld\r\n\r\n2\r\n00:00:00,500 --> 00:00:01,000\r\nAgain\r\n"


def test_parse_srt_and_vtt_preserves_times_and_text():
    result = parse("\ufeff" + SRT, "srt", 1)
    assert [s["start"] for s in result] == [0, 0.5]
    assert result[0]["text"] == "Hello\nworld" and result[0]["words"] == []
    vtt = "WEBVTT\n\nNOTE local note\nignored\n\ncue-1\n00:00.000 --> 00:00.500 align:start\n<v Alice>Hello</v>\n"
    assert parse(vtt, "vtt", 1)[0]["text"] == "<v Alice>Hello</v>"


@pytest.mark.parametrize(
    "text,format,duration",
    [
        ("", "srt", 1),
        (SRT, "srt", 0.2),
        ("x" * 524289, "srt", 1),
        (SRT.replace("00:00:00,500", "00:99:00,500"), "srt", 10000),
        (SRT.replace("00:00:00,000", "00:00:00,700"), "srt", 1),
        (
            "WEBVTT\n\nSTYLE\n::cue {color:red}\n\n00:00.000 --> 00:01.000\nHello",
            "vtt",
            1,
        ),
    ],
    # Explicit ids: the oversized payload would otherwise become a test id longer
    # than Windows allows in the PYTEST_CURRENT_TEST environment variable.
    ids=[
        "empty",
        "cue-past-duration",
        "oversized",
        "cue-past-limit",
        "end-before-start",
        "vtt-style-block",
    ],
)
def test_invalid_input_is_rejected(text, format, duration):
    with pytest.raises(ValueError):
        parse(text, format, duration)


def test_api_import_retains_existing_transcript_and_is_retry_safe(tmp_path):
    core = Core(tmp_path / "workspace")
    project = core.create_project("Subtitles")["id"]
    asset = core.import_file(project, wav(tmp_path / "input.wav", seconds=1))
    old = core.save_transcript(
        core.create_job(asset["id"], "transcribe"),
        {"language": "en", "segments": [{"start": 0, "end": 1, "text": "Original"}]},
    )
    payload = {
        "asset_id": asset["id"],
        "request_id": str(uuid.uuid4()),
        "text": SRT,
        "format": "srt",
        "language": "en",
    }
    with TestClient(create_app(core.db.root, "u" * 64)) as client:
        url = "/v1/transcripts/import"
        headers = {"Authorization": "Bearer " + "u" * 64}
        assert client.post(url, json=payload).status_code == 401
        first = client.post(url, json=payload, headers=headers)
        assert first.status_code == 201 and first.json()["id"] != old
        assert (
            client.post(url, json=payload, headers=headers).json()["id"]
            == first.json()["id"]
        )
        assert len(core.transcripts()) == 2
        assert (
            client.post(
                url,
                json={**payload, "text": SRT.replace("Again", "Changed")},
                headers=headers,
            ).status_code
            == 409
        )
        assert (
            client.post(
                url,
                json={
                    **payload,
                    "request_id": str(uuid.uuid4()),
                    "text": SRT.replace("01,000", "09,000"),
                },
                headers=headers,
            ).status_code
            == 409
        )
        assert len(core.transcripts()) == 2
        assert (
            core.transcript_revisions(first.json()["id"])["items"][0]["revision"] == 1
        )
