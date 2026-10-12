"""Engine cache, text chunking and mid-synthesis cancellation (fake engines only).

No real inference happens here: these tests cover the surrounding logic.
"""

import wave
from types import SimpleNamespace

import numpy as np
import pytest
from nexus_runtime.engines import kokoro, whisper
from nexus_runtime.engines.cache import CACHE, EngineCache


class FakeKokoro:
    def __init__(self):
        self.calls = []

    def get_voices(self):
        return ["af_test"]

    def create(self, text, voice, speed, lang):
        self.calls.append(text)
        return np.full(2400, 0.25, dtype="float32"), 24000


@pytest.fixture(autouse=True)
def clean_cache():
    CACHE.clear()
    yield
    CACHE.clear()


def options(text):
    return {"voice": "af_test", "text": text, "model_id": "kokoro-v1"}


def test_cache_builds_once_and_evicts_least_recently_used():
    cache, built = EngineCache(max_entries=2), []

    def make(name):
        def factory():
            built.append(name)
            return name

        return factory

    assert cache.get(("e", "a"), make("a")) == "a"
    assert cache.get(("e", "a"), make("a")) == "a"
    cache.get(("e", "b"), make("b"))
    cache.get(("e", "a"), make("a"))  # a is now most recent
    cache.get(("e", "c"), make("c"))  # evicts b
    assert built == ["a", "b", "c"]
    assert len(cache) == 2
    cache.get(("e", "b"), make("b"))
    assert built == ["a", "b", "c", "b"]


def test_invalidate_drops_only_matching_model_path():
    cache = EngineCache(max_entries=4)
    cache.get(("whisper", "/m/a", "cpu"), lambda: 1)
    cache.get(("whisper", "/m/a", "cuda"), lambda: 2)
    cache.get(("whisper", "/m/b", "cpu"), lambda: 3)
    assert cache.invalidate("/m/a") == 2
    assert len(cache) == 1


def test_split_text_respects_limit_and_keeps_all_words():
    text = "First sentence. Second one! " + "word " * 200 + "Last? " + "x" * 700
    chunks = kokoro.split_text(text, limit=100)
    assert all(0 < len(chunk) <= 100 for chunk in chunks)
    assert "".join("".join(chunks).split()) == "".join(text.split())
    assert kokoro.split_text("Short.") == ["Short."]


def test_synthesis_chunks_and_loads_model_once(tmp_path, monkeypatch):
    loads = []
    fake = FakeKokoro()
    monkeypatch.setattr(kokoro, "load_engine", lambda path: loads.append(path) or fake)
    text = " ".join(f"Sentence number {i}." for i in range(40))
    for name in ("one.wav", "two.wav"):
        target = tmp_path / name
        result = kokoro.synthesize(
            tmp_path, options(text), target, lambda _: None, lambda: False
        )
        with wave.open(str(target)) as audio:
            assert audio.getnframes() == 2400 * len(kokoro.split_text(text))
        assert result["sample_rate"] == 24000
    assert len(loads) == 1
    assert len(kokoro.split_text(text)) > 1


def test_cancel_between_chunks_stops_early_and_writes_nothing(tmp_path):
    fake = FakeKokoro()
    state = {"cancel": False}

    def progress(value):
        state["cancel"] = value > 0  # cancel after the first chunk completes

    target = tmp_path / "out.wav"
    text = " ".join(f"Sentence number {i}." for i in range(40))
    with pytest.raises(InterruptedError):
        kokoro.synthesize(
            tmp_path,
            options(text),
            target,
            progress,
            lambda: state["cancel"],
            engine=fake,
        )
    assert len(fake.calls) == 1
    assert not target.exists()


def test_unknown_voice_is_a_domain_error(tmp_path):
    bad = options("Hi.") | {"voice": "af_missing"}
    with pytest.raises(ValueError, match="voice_not_found"):
        kokoro.synthesize(
            tmp_path,
            bad,
            tmp_path / "x.wav",
            lambda _: None,
            lambda: False,
            engine=FakeKokoro(),
        )


def test_whisper_model_is_cached_per_device(tmp_path, monkeypatch):
    loads = []

    class Model:
        def transcribe(self, *args, **kwargs):
            info = SimpleNamespace(
                duration=1.0, language="en", language_probability=1.0
            )
            return iter([]), info

    def fake_load(path, device):
        loads.append(device)
        return Model()

    monkeypatch.setattr(whisper, "load_model", fake_load)
    opts = {"model_id": "whisper-tiny", "device": "cpu"}
    for _ in range(3):
        whisper.transcribe(
            tmp_path / "a.wav", tmp_path, opts, lambda _: None, lambda: False
        )
    assert loads == ["cpu"]
    whisper.transcribe(
        tmp_path / "a.wav",
        tmp_path,
        {**opts, "device": "cuda"},
        lambda _: None,
        lambda: False,
    )
    assert loads == ["cpu", "cuda"]


def test_uninstalling_a_model_drops_its_cached_engine(tmp_path):
    from unittest.mock import patch

    from test_models import DATA, Response, manager

    m = manager(tmp_path)
    with patch("urllib.request.urlopen", return_value=Response(DATA)):
        m.action("test", "install")
        m.thread.join(5)
    folder = m.directory("test")
    CACHE.get(("whisper", str(folder), "cpu"), lambda: object())
    assert len(CACHE) == 1
    m.action("test", "uninstall")
    assert len(CACHE) == 0
