"""Narration production from explicit chapter text or edited transcript segments."""

import tempfile
import wave
from pathlib import Path

from .engines.kokoro import load_engine, synthesize
from .errors import DomainError
from .media import probe


class TemporarySources:
    """Expose only generated temporary clips to the existing bounded mixer."""

    def __init__(self, project_id):
        self.project_id = project_id
        self.sources = {}

    def add(self, path):
        identifier = str(len(self.sources))
        self.sources[identifier] = (
            path,
            {**probe(path), "id": identifier, "project_id": self.project_id},
        )
        return self.sources[identifier][1]

    def asset(self, identifier):
        return self.sources[identifier][1]

    def asset_path(self, identifier):
        return self.sources[identifier][0]


def audiobook(core, models, job, options, progress, cancelled):

    folder = models.directory(options["model_id"])
    engine = load_engine(folder)
    with tempfile.TemporaryDirectory(dir=core.db.root, prefix="narration-") as temp:
        target = Path(temp) / "audiobook.wav"
        chapters = []
        frames = 0
        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(24000)
            for index, chapter in enumerate(options["chapters"]):
                if cancelled():
                    raise InterruptedError
                path = Path(temp) / f"{index}.wav"
                settings = {**options, "text": chapter["text"]}
                synthesize(folder, settings, path, lambda _: None, cancelled, engine)
                start = frames / 24000
                with wave.open(str(path), "rb") as audio:
                    while block := audio.readframes(8192):
                        if cancelled():
                            raise InterruptedError
                        output.writeframes(block)
                        frames += len(block) // 2
                chapters.append(
                    {"title": chapter["title"], "start": start, "end": frames / 24000}
                )
                if index < len(options["chapters"]) - 1:
                    gap = round(options.get("gap", 1) * 24000)
                    output.writeframes(b"\0\0" * gap)
                    frames += gap
                progress((index + 1) / len(options["chapters"]))
        asset = core.import_file(job["project_id"], target, "Audiobook.wav")
        return {
            "asset_id": asset["id"],
            "chapters": chapters,
            "duration": frames / 24000,
            "sample_rate": 24000,
        }


def dubbing(core, models, job, options, progress, cancelled):

    from .timeline import render

    folder = models.directory(options["model_id"])
    engine = load_engine(folder)
    transcript = next(
        (
            t
            for t in core.transcripts()
            if t["id"] == options["transcript_id"]
            and t["project_id"] == job["project_id"]
        ),
        None,
    )
    if not transcript:
        raise DomainError("transcript_not_found")
    segments = [s for s in transcript["segments"] if s["text"].strip()]
    if not segments or len(segments) > 64:
        raise DomainError("dubbing_segment_limit")
    clips = []
    overruns = []
    sources = TemporarySources(job["project_id"])
    with tempfile.TemporaryDirectory(dir=core.db.root, prefix="dubbing-") as temp:
        for index, segment in enumerate(segments):
            if cancelled():
                raise InterruptedError
            path = Path(temp) / f"segment-{index + 1}.wav"
            synthesize(
                folder,
                {**options, "text": segment["text"]},
                path,
                lambda _: None,
                cancelled,
                engine,
            )
            asset = sources.add(path)
            if asset["duration"] > segment["end"] - segment["start"]:
                overruns.append(
                    {
                        "segment": index + 1,
                        "excess_seconds": asset["duration"]
                        - (segment["end"] - segment["start"]),
                    }
                )
            clips.append(
                {
                    "asset_id": asset["id"],
                    "offset": segment["start"],
                    "trim_start": 0,
                    "trim_end": asset["duration"],
                    "gain": 1,
                    "fade_in": 0,
                    "fade_out": 0,
                }
            )
            progress(0.8 * (index + 1) / len(segments))
        target = Path(temp) / "dubbing.wav"
        result = render(
            clips,
            sources,
            job["project_id"],
            target,
            lambda p: progress(0.8 + 0.2 * p),
            cancelled,
        )
        result["asset_id"] = core.import_file(job["project_id"], target, "Dubbing.wav")[
            "id"
        ]
        result["overruns"] = overruns
        result["source_transcript_revision"] = transcript["revision"]
        return result
