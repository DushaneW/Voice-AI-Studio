"""Local-path-only ASR adapter; no implicit Hugging Face downloads."""


def load_model(model_path, device):
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(model_path),
        device=device,
        compute_type="int8" if device == "cpu" else "float16",
        local_files_only=True,
        cpu_threads=4,
    )


def transcribe(path, model_path, options, progress, cancelled):
    from .cache import CACHE

    if cancelled():
        raise InterruptedError
    device = options.get("device", "cpu")
    model = CACHE.get(
        ("whisper", str(model_path), device), lambda: load_model(model_path, device)
    )
    segments, info = model.transcribe(
        str(path),
        language=options.get("language") or None,
        beam_size=5,
        word_timestamps=True,
        vad_filter=False,
    )
    output = []
    for segment in segments:
        if cancelled():
            raise InterruptedError
        output.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": [
                    {
                        "start": w.start,
                        "end": w.end,
                        "text": w.word,
                        "probability": w.probability,
                    }
                    for w in (segment.words or [])
                ],
            }
        )
        progress(min(0.99, segment.end / max(info.duration, 0.001)))
    if cancelled():
        raise InterruptedError
    return {
        "segments": output,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration": info.duration,
        "model": options["model_id"],
        "device": device,
    }
