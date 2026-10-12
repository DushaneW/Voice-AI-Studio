"""Shared persisted-data validation for API, inference and portable restores."""

import math

from .errors import DomainError


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_segments(segments, duration=None):
    if not isinstance(segments, list) or len(segments) > 10000:
        raise DomainError("invalid_transcript_segments")
    previous = -1.0
    for segment in segments:
        if not isinstance(segment, dict):
            raise DomainError("invalid_transcript_segment")
        start, end, text = (segment.get(k) for k in ("start", "end", "text"))
        if (
            not number(start)
            or not number(end)
            or start < 0
            or end <= start
            or start < previous
            or (duration is not None and end > duration + 0.05)
            or not isinstance(text, str)
            or len(text) > 10000
        ):
            raise DomainError("invalid_transcript_segment")
        speaker = segment.get("speaker")
        if speaker is not None and (
            not isinstance(speaker, str)
            or not speaker.strip()
            or len(speaker) > 80
            or speaker != speaker.strip()
            or any(ord(c) < 32 for c in speaker)
        ):
            raise DomainError("invalid_speaker")
        previous = start
    return segments


def merge_transcript_edit(original, edited, duration):
    """Never trust client word timing; retain it only for unchanged segments."""
    validate_segments(edited, duration)
    unchanged = {(s["start"], s["end"], s["text"]): s for s in original}
    result = []
    for segment in edited:
        fields = {k: segment[k] for k in ("start", "end", "text")}
        old = unchanged.get(tuple(fields.values()))
        if old is not None:
            result.append({**old, **fields})
        else:
            result.append({**fields, "words": [], "word_timestamps_valid": False})
        if "speaker" in segment:
            if segment["speaker"] is None:
                result[-1].pop("speaker", None)
            else:
                result[-1]["speaker"] = segment["speaker"]
    return result


def validate_document(core, project_id, kind, content):
    import json

    if kind not in {"timeline", "audiobook", "dubbing", "project"}:
        raise DomainError("invalid_document_kind")
    if not isinstance(content, dict):
        raise DomainError("invalid_document")
    if kind == "project":
        limits = {"description": 5000, "author": 120, "language": 35}
        if set(content) - {*limits, "tags"}:
            raise DomainError("invalid_project_metadata")
        for key, limit in limits.items():
            if (
                not isinstance(content.get(key, ""), str)
                or len(content.get(key, "")) > limit
            ):
                raise DomainError("invalid_project_metadata")
        tags = content.get("tags", [])
        if (
            not isinstance(tags, list)
            or len(tags) > 20
            or any(
                not isinstance(tag, str)
                or not 1 <= len(tag.strip()) <= 60
                or any(ord(char) < 32 for char in tag)
                for tag in tags
            )
        ):
            raise DomainError("invalid_project_metadata")
        return {
            **{key: content.get(key, "") for key in limits},
            "tags": list(dict.fromkeys(tag.strip() for tag in tags)),
        }
    if kind == "timeline":
        from .timeline import validate_tracks

        validate_tracks(content.get("tracks"), [])
    try:
        size = len(json.dumps(content, allow_nan=False).encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise DomainError("invalid_document") from exc
    if size > 1024 * 1024:
        raise DomainError("document_too_large")
    if kind == "timeline":
        from .timeline import validate

        if content.get("sample_rate", 24000) not in (
            24000,
            44100,
            48000,
        ) or content.get("channels", 1) not in (1, 2):
            raise DomainError("invalid_render_format")
        clips = content.get("clips", [])
        if not isinstance(clips, list) or len(clips) > 64:
            raise DomainError("invalid_document")
        normalized = []
        for clip in clips:
            if not isinstance(clip, dict) or not isinstance(clip.get("asset_id"), str):
                raise DomainError("invalid_document")
            asset = core.asset(clip["asset_id"])
            candidate = {
                "offset": 0,
                "trim_start": 0,
                "trim_end": asset["duration"],
                "gain": 1,
                "fade_in": 0,
                "fade_out": 0,
                **clip,
            }
            if not all(
                number(candidate[k])
                for k in (
                    "offset",
                    "trim_start",
                    "trim_end",
                    "gain",
                    "fade_in",
                    "fade_out",
                )
            ):
                raise DomainError("invalid_clip")
            if candidate["fade_in"] > 60 or candidate["fade_out"] > 60:
                raise DomainError("invalid_clip")
            normalized.append(candidate)
        if normalized:
            validate(normalized, core, project_id)
        tracks = validate_tracks(content.get("tracks"), normalized)
        return {
            **content,
            "clips": normalized,
            **({"tracks": list(tracks.values())} if "tracks" in content else {}),
        }
    chapters = content.get("chapters", [])
    if not isinstance(chapters, list) or len(chapters) > 50:
        raise DomainError("invalid_document")
    for chapter in chapters:
        if (
            not isinstance(chapter, dict)
            or not isinstance(chapter.get("title"), str)
            or len(chapter["title"]) > 120
            or not isinstance(chapter.get("text"), str)
            or len(chapter["text"]) > 5000
        ):
            raise DomainError("invalid_document")
    gap = content.get("gap", 1)
    if not number(gap) or not 0 <= gap <= 10:
        raise DomainError("invalid_document")
    voice = content.get("voice", "")
    if not isinstance(voice, str) or len(voice) > 120:
        raise DomainError("invalid_document")
    transcript_id = content.get("transcriptId", "")
    if not isinstance(transcript_id, str):
        raise DomainError("invalid_document")
    if transcript_id and not core.db.rows(
        "SELECT id FROM transcripts WHERE id=? AND project_id=?",
        (transcript_id, project_id),
    ):
        raise DomainError("transcript_project_mismatch")
    return content
