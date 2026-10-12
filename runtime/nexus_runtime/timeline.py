"""Bounded-memory PCM mixer with trims, placement, gain and fades."""

import math
import wave
from contextlib import ExitStack

from .errors import DomainError

RATE = 24000
BLOCK = 1024


def validate(clips, core, project_id):
    if not clips or len(clips) > 64:
        raise DomainError("timeline_clip_limit")
    for clip in clips:
        asset = core.asset(clip["asset_id"])
        if asset["project_id"] != project_id:
            raise DomainError("asset_project_mismatch")
        for key in ("offset", "trim_start", "trim_end", "gain", "fade_in", "fade_out"):
            if not math.isfinite(clip[key]) or clip[key] < 0:
                raise DomainError("invalid_clip")
        length = clip["trim_end"] - clip["trim_start"]
        if (
            length <= 0
            or clip["trim_end"] > asset["duration"] + 0.0001
            or clip["offset"] + length > 3600
            or clip["gain"] > 4
        ):
            raise DomainError("invalid_clip")
    return max(c["offset"] + c["trim_end"] - c["trim_start"] for c in clips)


def validate_tracks(tracks, clips):
    if tracks is None:
        tracks = [{"id": "main", "name": "Main"}]
    if not isinstance(tracks, list) or not 1 <= len(tracks) <= 32:
        raise DomainError("invalid_tracks")
    result = {}
    for track in tracks:
        if not isinstance(track, dict):
            raise DomainError("invalid_tracks")
        if set(track) - {
            "id",
            "name",
            "volume",
            "pan",
            "muted",
            "solo",
            "locked",
            "visible",
        }:
            raise DomainError("invalid_tracks")
        identifier = track.get("id")
        if (
            not isinstance(identifier, str)
            or not 1 <= len(identifier) <= 80
            or identifier in result
        ):
            raise DomainError("invalid_tracks")
        name = track.get("name", identifier)
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise DomainError("invalid_tracks")
        normalized = {
            "id": identifier,
            "name": name,
            "volume": 1,
            "pan": 0,
            "muted": False,
            "solo": False,
            "locked": False,
            "visible": True,
            **track,
        }
        for field, minimum, maximum in [("volume", 0, 4), ("pan", -1, 1)]:
            value = normalized[field]
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not minimum <= value <= maximum
            ):
                raise DomainError("invalid_tracks")
        if any(
            not isinstance(normalized[key], bool)
            for key in ("muted", "solo", "locked", "visible")
        ):
            raise DomainError("invalid_tracks")
        result[identifier] = normalized
    if any(
        not isinstance(clip.get("track_id", "main"), str)
        or clip.get("track_id", "main") not in result
        for clip in clips
    ):
        raise DomainError("track_not_found")
    return result


def resample(reader, positions, output_rate, channels):
    """Windowed-sinc interpolation with a low-pass cutoff before decimation.

    Read guard samples around each block, so filter state does not reset at
    block boundaries. Work and memory are bounded by block size and rate ratio.
    """
    import numpy as np

    cutoff = min(1.0, output_rate / reader.getframerate())
    if cutoff < 1:
        cutoff *= 0.94
    radius = math.ceil(32 / cutoff)
    centers = np.floor(positions).astype(np.int64)
    indices = centers[:, None] + np.arange(-radius + 1, radius + 1)
    distance = positions[:, None] - indices
    weights = cutoff * np.sinc(cutoff * distance)
    weights *= np.where(
        np.abs(distance) < radius, 0.5 + 0.5 * np.cos(np.pi * distance / radius), 0
    )
    weights /= weights.sum(axis=1, keepdims=True)
    first = max(0, int(indices.min()))
    last = min(reader.getnframes(), int(indices.max()) + 1)
    reader.setpos(first)
    data = np.frombuffer(reader.readframes(last - first), dtype="<i2").astype(
        np.float64
    )
    data = data.reshape(-1, reader.getnchannels()) / 32768
    if channels == 1:
        data = data.mean(axis=1, keepdims=True)
    elif reader.getnchannels() == 1:
        data = np.repeat(data, 2, axis=1)
    elif reader.getnchannels() != 2:
        raise DomainError("stereo_source_required")
    valid = (indices >= first) & (indices < last)
    samples = data[np.clip(indices - first, 0, len(data) - 1)]
    return np.einsum("ij,ijk->ik", weights * valid, samples)


def render(
    clips,
    core,
    project_id,
    target,
    progress,
    cancelled,
    sample_rate=RATE,
    channels=1,
    tracks=None,
):
    import numpy as np

    if sample_rate not in (24000, 44100, 48000) or channels not in (1, 2):
        raise DomainError("invalid_render_format")
    duration = validate(clips, core, project_id)
    track_map = validate_tracks(tracks, clips)
    any_solo = any(track["solo"] for track in track_map.values())
    frames = math.ceil(duration * sample_rate)
    if frames * channels * 2 + 44 > 512 * 1024 * 1024:
        raise DomainError("render_size_limit")
    clipped_samples = 0
    with ExitStack() as stack:
        readers = [
            stack.enter_context(wave.open(str(core.asset_path(c["asset_id"])), "rb"))
            for c in clips
        ]
        output = stack.enter_context(wave.open(str(target), "wb"))
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        for start in range(0, frames, BLOCK):
            if cancelled():
                raise InterruptedError
            size = min(BLOCK, frames - start)
            times = (np.arange(size) + start) / sample_rate
            mixed = np.zeros((size, channels), dtype=np.float64)
            for clip, reader in zip(clips, readers, strict=True):
                track = track_map[clip.get("track_id", "main")]
                if track["muted"] or (any_solo and not track["solo"]):
                    continue
                length = clip["trim_end"] - clip["trim_start"]
                local = times - clip["offset"]
                mask = (local >= 0) & (local < length)
                if not mask.any():
                    continue
                positions = (local[mask] + clip["trim_start"]) * reader.getframerate()
                values = resample(reader, positions, sample_rate, channels)
                envelope = np.ones(len(values))
                if clip["fade_in"] > 0:
                    envelope *= np.minimum(1, local[mask] / clip["fade_in"])
                if clip["fade_out"] > 0:
                    envelope *= np.minimum(1, (length - local[mask]) / clip["fade_out"])
                if channels == 2:
                    values *= np.array(
                        [min(1, 1 - track["pan"]), min(1, 1 + track["pan"])]
                    )
                mixed[mask] += (
                    values * clip["gain"] * track["volume"] * envelope[:, None]
                )
            clipped_samples += int(np.count_nonzero(np.abs(mixed) > 1))
            output.writeframes((np.clip(mixed, -1, 1) * 32767).astype("<i2").tobytes())
            progress((start + size) / frames)
    return {
        "duration": frames / sample_rate,
        "sample_rate": sample_rate,
        "channels": channels,
        "clipped_samples": clipped_samples,
    }
