import pytest
from nexus_runtime.exports import subtitles, timestamp


def test_timestamp_carry_and_subtitles():
    assert timestamp(59.9996) == "00:01:00,000"
    segments = [{"start": 1.25, "end": 2.5, "text": "Hello"}]
    assert subtitles(segments, "srt") == "1\n00:00:01,250 --> 00:00:02,500\nHello\n"
    assert subtitles(segments, "vtt").startswith("WEBVTT\n\n1\n00:00:01.250")
    assert subtitles(segments, "txt") == "Hello\n"
    with pytest.raises(ValueError):
        subtitles(segments, "exe")
