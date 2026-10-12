from .errors import DomainError

"""Pure subtitle serializers; source timestamps remain unchanged."""


def timestamp(seconds: float, separator: str = ",") -> str:
    milliseconds = round(seconds * 1000)
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    sec, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{sec:02d}{separator}{ms:03d}"


def subtitles(segments: list[dict], format: str) -> str:
    if format == "json":
        import json

        return (
            json.dumps(
                {"schema": 1, "segments": segments}, ensure_ascii=False, indent=2
            )
            + "\n"
        )
    if format == "txt":
        return "\n".join(s["text"] for s in segments) + "\n"
    if format not in {"srt", "vtt"}:
        raise DomainError("unsupported_export_format")
    separator = "." if format == "vtt" else ","
    blocks = []
    for index, segment in enumerate(segments, 1):
        clean = (
            segment["text"].replace("\r", "").replace("\n\n", "\n").replace("-->", "→")
        )
        blocks.append(
            f"{index}\n{timestamp(segment['start'], separator)} --> {timestamp(segment['end'], separator)}\n{clean}"
        )
    return ("WEBVTT\n\n" if format == "vtt" else "") + "\n\n".join(blocks) + "\n"
