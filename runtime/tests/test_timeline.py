import wave

import numpy as np
import pytest
from nexus_runtime.core import Core
from nexus_runtime.timeline import render, validate


def setup(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Edit")
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(np.full(2400, 8192, dtype="<i2").tobytes())
    asset = core.import_file(project["id"], source)
    clip = {
        "asset_id": asset["id"],
        "offset": 0.1,
        "trim_start": 0,
        "trim_end": 0.1,
        "gain": 0.5,
        "fade_in": 0,
        "fade_out": 0,
    }
    return core, project, clip


def test_real_mix_timing_gain_and_output(tmp_path):
    core, p, c = setup(tmp_path)
    out = tmp_path / "render.wav"
    result = render([c], core, p["id"], out, lambda _: None, lambda: False)
    assert result["duration"] == 0.2
    with wave.open(str(out), "rb") as audio:
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2")
    assert np.max(np.abs(samples[:2400])) == 0
    assert abs(int(samples[3000]) - 4096) <= 1


def test_cancel_and_cross_project_rejected(tmp_path):
    core, p, c = setup(tmp_path)
    with pytest.raises(InterruptedError):
        render([c], core, p["id"], tmp_path / "out.wav", lambda _: None, lambda: True)
    other = core.create_project("Other")
    with pytest.raises(ValueError, match="asset_project_mismatch"):
        validate([c], core, other["id"])
    with pytest.raises(ValueError, match="invalid_clip"):
        validate([{**c, "trim_end": 2}], core, p["id"])


def test_document_revision_and_restore(tmp_path):
    core, p, c = setup(tmp_path)
    assert core.document(p["id"], "timeline")["revision"] == 0
    saved = core.save_document(p["id"], "timeline", {"clips": [c]}, 0)
    assert saved["revision"] == 1
    with pytest.raises(ValueError, match="revision_conflict"):
        core.save_document(p["id"], "timeline", {}, 0)
    assert Core(tmp_path / "data").document(p["id"], "timeline")["content"][
        "clips"
    ] == [c]


def test_downsampling_suppresses_alias_and_keeps_stereo(tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Audio quality")
    source = tmp_path / "stereo.wav"
    times = np.arange(48000) / 48000
    samples = (
        np.column_stack(
            (np.sin(2 * np.pi * 18000 * times), np.sin(2 * np.pi * 1000 * times))
        )
        * 0.5
    )
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes((samples * 32767).astype("<i2").tobytes())
    asset = core.import_file(project["id"], source)
    clip = {
        "asset_id": asset["id"],
        "offset": 0,
        "trim_start": 0,
        "trim_end": 1,
        "gain": 1,
        "fade_in": 0,
        "fade_out": 0,
    }
    target = tmp_path / "filtered.wav"
    result = render(
        [clip],
        core,
        project["id"],
        target,
        lambda _: None,
        lambda: False,
        sample_rate=24000,
        channels=2,
    )
    with wave.open(str(target), "rb") as audio:
        assert audio.getframerate() == 24000 and audio.getnchannels() == 2
        output = (
            np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").reshape(
                -1, 2
            )
            / 32768
        )
    center = output[100:-100]
    assert (
        np.sqrt(np.mean(center[:, 0] ** 2)) < 0.001
    )  # Aliased 6 kHz must be suppressed.
    assert 0.34 < np.sqrt(np.mean(center[:, 1] ** 2)) < 0.36
    assert result["channels"] == 2
    preserved = tmp_path / "preserved.wav"
    render(
        [clip],
        core,
        project["id"],
        preserved,
        lambda _: None,
        lambda: False,
        sample_rate=48000,
        channels=2,
    )
    with wave.open(str(preserved), "rb") as audio:
        output = (
            np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").reshape(
                -1, 2
            )
            / 32768
        )
    assert np.max(np.abs(output - samples)) < 0.0001


def test_tracks_mute_solo_gain_and_stereo_balance_affect_render(tmp_path):
    core, project, clip = setup(tmp_path)
    clip = {**clip, "offset": 0, "track_id": "voice"}
    tracks = [
        {"id": "voice", "name": "Voice", "volume": 0.5, "pan": -1},
        {"id": "music", "name": "Music", "muted": True},
    ]
    output = tmp_path / "tracks.wav"
    render(
        [clip, {**clip, "track_id": "music"}],
        core,
        project["id"],
        output,
        lambda _: None,
        lambda: False,
        channels=2,
        tracks=tracks,
    )
    with wave.open(str(output), "rb") as audio:
        samples = np.frombuffer(
            audio.readframes(audio.getnframes()), dtype="<i2"
        ).reshape(-1, 2)
    assert abs(int(samples[100, 0]) - 2048) <= 1
    assert np.max(np.abs(samples[:, 1])) == 0
    tracks[1] = {"id": "music", "name": "Music", "solo": True, "volume": 0}
    render(
        [clip, {**clip, "track_id": "music"}],
        core,
        project["id"],
        output,
        lambda _: None,
        lambda: False,
        channels=2,
        tracks=tracks,
    )
    with wave.open(str(output), "rb") as audio:
        assert not any(audio.readframes(audio.getnframes()))


@pytest.mark.parametrize(
    "tracks",
    [
        [{"id": "x"}, {"id": "x"}],
        [{"id": "main", "volume": float("nan")}],
        [{"id": "main", "muted": "false"}],
        [{"id": "absent"}],
    ],
)
def test_invalid_track_configuration_is_rejected(tmp_path, tracks):
    core, project, clip = setup(tmp_path)
    with pytest.raises(ValueError, match="invalid_tracks|track_not_found"):
        core.save_document(
            project["id"], "timeline", {"clips": [clip], "tracks": tracks}, 0
        )


def test_transcript_json_export_preserves_words_and_unicode():
    import json

    from nexus_runtime.exports import subtitles

    segments = [
        {
            "start": 0,
            "end": 1,
            "text": "Zażółć",
            "words": [{"text": "Zażółć", "start": 0, "end": 1}],
        }
    ]
    result = json.loads(subtitles(segments, "json"))
    assert result == {"schema": 1, "segments": segments}
