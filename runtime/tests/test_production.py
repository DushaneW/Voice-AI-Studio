import wave
from types import SimpleNamespace

import pytest
from nexus_runtime.core import Core
from nexus_runtime.production import audiobook, dubbing
from test_workflow import wav


def setup_engine(monkeypatch, tmp_path):
    from nexus_runtime import production

    monkeypatch.setattr(production, "load_engine", lambda _: object())

    def synthesize(_folder, _settings, path, _progress, _cancelled, _engine):
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            output.writeframes(b"\0\0" * 4800)

    monkeypatch.setattr(production, "synthesize", synthesize)
    return SimpleNamespace(directory=lambda _: tmp_path)


def test_audiobook_chapter_times_include_gaps(monkeypatch, tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Book")
    result = audiobook(
        core,
        setup_engine(monkeypatch, tmp_path),
        {"project_id": project["id"]},
        {
            "model_id": "test",
            "chapters": [{"title": "One", "text": "A"}, {"title": "Two", "text": "B"}],
            "gap": 0.5,
        },
        lambda _: None,
        lambda: False,
    )
    assert result["duration"] == 0.9
    assert result["chapters"] == [
        {"title": "One", "start": 0, "end": 0.2},
        {"title": "Two", "start": 0.7, "end": 0.9},
    ]
    assert core.asset(result["asset_id"])["name"] == "Audiobook.wav"


def test_dubbing_does_not_import_intermediate_segments(monkeypatch, tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Dub")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    transcript = core.save_transcript(
        job,
        {
            "language": "en",
            "segments": [
                {"start": 0, "end": 0.1, "text": "A"},
                {"start": 0.5, "end": 0.7, "text": "B"},
            ],
        },
    )
    result = dubbing(
        core,
        setup_engine(monkeypatch, tmp_path),
        {"project_id": project["id"]},
        {"model_id": "test", "transcript_id": transcript},
        lambda _: None,
        lambda: False,
    )
    assert len(core.active_assets(project["id"])) == 2
    assert result["overruns"][0]["excess_seconds"] == pytest.approx(0.1)
    assert core.asset(result["asset_id"])["name"] == "Dubbing.wav"
    assert not list(core.db.root.glob("dubbing-*"))
    other = core.create_project("Other")
    with pytest.raises(ValueError, match="transcript_not_found"):
        dubbing(
            core,
            setup_engine(monkeypatch, tmp_path),
            {"project_id": other["id"]},
            {"model_id": "test", "transcript_id": transcript},
            lambda _: None,
            lambda: False,
        )


def test_cancelled_dubbing_leaves_no_generated_assets(monkeypatch, tmp_path):
    core = Core(tmp_path / "data")
    project = core.create_project("Cancel")
    asset = core.import_file(project["id"], wav(tmp_path / "source.wav", seconds=1))
    job = core.create_job(asset["id"], "transcribe")
    transcript = core.save_transcript(
        job, {"language": "en", "segments": [{"start": 0, "end": 0.5, "text": "A"}]}
    )
    with pytest.raises(InterruptedError):
        dubbing(
            core,
            setup_engine(monkeypatch, tmp_path),
            {"project_id": project["id"]},
            {"model_id": "test", "transcript_id": transcript},
            lambda _: None,
            lambda: True,
        )
    assert len(core.active_assets(project["id"])) == 1
    assert not list(core.db.root.glob("dubbing-*"))
