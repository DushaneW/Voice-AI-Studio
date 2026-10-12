"""Bounded, streaming PCM WAV analysis. No FFmpeg or ML inference is simulated."""

from __future__ import annotations

import array
import hashlib
import math
import sys
import wave
from pathlib import Path

MAX_BYTES = 512 * 1024 * 1024


class MediaError(ValueError):
    pass


def probe(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise MediaError("media_size_or_path")
    try:
        with wave.open(str(path), "rb") as stream:
            if stream.getsampwidth() != 2 or stream.getcomptype() != "NONE":
                raise MediaError("pcm16_required")
            frames, rate, channels = (
                stream.getnframes(),
                stream.getframerate(),
                stream.getnchannels(),
            )
            if not frames or not 8000 <= rate <= 192000 or not 1 <= channels <= 8:
                raise MediaError("invalid_wav")
            # Verify data length by streaming rather than trusting the WAV header.
            remaining = frames
            while remaining:
                data = stream.readframes(min(remaining, 65536))
                if not data or len(data) % (channels * 2):
                    raise MediaError("truncated_wav")
                remaining -= len(data) // (channels * 2)
            return {
                "duration": frames / rate,
                "sample_rate": rate,
                "channels": channels,
                "frames": frames,
                "size": path.stat().st_size,
            }
    except (wave.Error, EOFError, OSError) as exc:
        raise MediaError("invalid_wav") from exc


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def analyze(path: Path, progress, cancelled) -> dict:
    info = probe(path)
    bins = []
    peak, square_sum, sample_count, frames_read = 0, 0.0, 0, 0
    bin_frames = max(1, math.ceil(info["frames"] / 640))
    with wave.open(str(path), "rb") as stream:
        while block := stream.readframes(bin_frames):
            if cancelled():
                raise InterruptedError
            samples = array.array("h")
            samples.frombytes(block)
            if sys.byteorder != "little":
                samples.byteswap()
            local_peak = max(abs(sample) for sample in samples)
            peak = max(peak, local_peak)
            square_sum += sum((sample / 32768.0) ** 2 for sample in samples)
            sample_count += len(samples)
            frames_read += len(samples) // info["channels"]
            bins.append(round(local_peak / 32768.0, 6))
            progress(min(1.0, frames_read / info["frames"]))
    rms = math.sqrt(square_sum / sample_count) if sample_count else 0
    return dict(
        peaks=bins,
        peak_dbfs=20 * math.log10(peak / 32768.0) if peak else None,
        rms_dbfs=20 * math.log10(rms) if rms else None,
        **info,
    )
