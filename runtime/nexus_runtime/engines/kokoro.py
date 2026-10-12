"""Kokoro ONNX synthesis into a managed PCM16 WAV, without remote execution."""

import re
import wave

from ..errors import DomainError


def load_engine(model_path):
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    ort.disable_telemetry_events()
    settings = ort.SessionOptions()
    settings.intra_op_num_threads = 4
    settings.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(model_path / "kokoro-v1.0.int8.onnx"),
        sess_options=settings,
        providers=["CPUExecutionProvider"],
    )
    return Kokoro.from_session(session, str(model_path / "voices-v1.0.bin"))


CHUNK_CHARS = 300
_SENTENCE_END = re.compile(r"(?<=[.!?\u3002\uff01\uff1f\u2026])\s+")


def split_text(text, limit=CHUNK_CHARS):
    """Split text at sentence ends into chunks of at most limit characters.

    A single sentence longer than limit is cut at whitespace (or hard-cut when
    it has none), so no chunk exceeds limit and no text is dropped.
    """
    chunks, current = [], ""
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        chunks.append(current)
    return chunks


def synthesize(model_path, options, target, progress, cancelled, engine=None):
    import numpy as np

    from .cache import CACHE

    if cancelled():
        raise InterruptedError
    model = engine or CACHE.get(
        ("kokoro", str(model_path)), lambda: load_engine(model_path)
    )
    if options["voice"] not in model.get_voices():
        raise DomainError("voice_not_found")
    parts, rate = [], None
    chunks = split_text(options["text"]) or [options["text"]]
    for index, chunk in enumerate(chunks):
        # Cancellation is checked between chunks: one chunk is the longest
        # uninterruptible native call.
        if cancelled():
            raise InterruptedError
        samples, rate = model.create(
            chunk,
            voice=options["voice"],
            speed=options.get("speed", 1.0),
            lang=options.get("language", "en-us"),
        )
        parts.append(samples)
        progress(min(0.99, (index + 1) / len(chunks)))
    if cancelled():
        raise InterruptedError
    samples = np.concatenate(parts) if len(parts) > 1 else parts[0]
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(target), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm.tobytes())
    progress(1)
    return {
        "sample_rate": rate,
        "duration": len(samples) / rate,
        "voice": options["voice"],
        "model": options["model_id"],
    }


def voices(model_path):
    import numpy as np

    with np.load(model_path / "voices-v1.0.bin", allow_pickle=False) as data:
        return [
            {
                "id": name,
                "language": {
                    "a": "en-us",
                    "b": "en-gb",
                    "f": "fr-fr",
                    "j": "ja",
                    "z": "zh",
                    "e": "es",
                    "h": "hi",
                    "i": "it",
                    "p": "pt-br",
                }.get(name[0], "unknown"),
                "source": "Kokoro v1.0",
            }
            for name in sorted(data.files)
        ]
