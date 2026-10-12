"""Strict bounded SRT/WebVTT text import; no styling or executable markup."""

import re

from .errors import DomainError
from .validation import validate_segments

MAX_BYTES = 512 * 1024


def _seconds(value: str, format: str) -> float:
    separator = r"\." if format == "vtt" else ","
    hours = r"(?:(\d{2,}):)?" if format == "vtt" else r"(\d{2,}):"
    match = re.fullmatch(hours + r"([0-5]\d):([0-5]\d)" + separator + r"(\d{3})", value)
    if not match:
        raise DomainError("invalid_subtitles")
    h, m, s, ms = match.groups()
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse(text: str, format: str, duration: float) -> list[dict]:
    if format not in {"srt", "vtt"} or len(text.encode("utf-8")) > MAX_BYTES:
        raise DomainError("invalid_subtitles")
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in text:
        raise DomainError("invalid_subtitles")
    blocks = re.split(r"\n[ \t]*\n", text)
    if format == "vtt":
        if not blocks or not re.fullmatch(r"WEBVTT(?:[ \t][^\n]*)?", blocks[0]):
            raise DomainError("invalid_subtitles")
        blocks = blocks[1:]
    if len(blocks) > 10000:
        raise DomainError("invalid_subtitles")
    segments = []
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue
        if format == "vtt" and (lines[0] == "NOTE" or lines[0].startswith("NOTE ")):
            continue
        if format == "vtt" and lines[0] in {"STYLE", "REGION"}:
            raise DomainError("subtitle_styling_unsupported")
        if "-->" not in lines[0]:
            if format == "srt" and not lines[0].isdigit():
                raise DomainError("invalid_subtitles")
            lines = lines[1:]
        if len(lines) < 2:
            raise DomainError("invalid_subtitles")
        timing = re.fullmatch(r"(\S+)\s+-->\s+(\S+)(?:[ \t]+[^\n]*)?", lines[0])
        if not timing:
            raise DomainError("invalid_subtitles")
        content = "\n".join(lines[1:]).strip()
        if not content:
            raise DomainError("invalid_subtitles")
        segments.append(
            {
                "start": _seconds(timing[1], format),
                "end": _seconds(timing[2], format),
                "text": content,
                "words": [],
                "word_timestamps_valid": False,
            }
        )
    if not segments:
        raise DomainError("invalid_subtitles")
    validate_segments(segments, duration)
    return segments
