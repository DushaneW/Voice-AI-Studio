"""Local-only FFmpeg decoding; no shell, network inputs or persistent intermediates."""

import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .media import MAX_BYTES, MediaError, probe


@contextmanager
def decoded_audio(source: Path, temporary_root: Path):
    if source.is_symlink():
        raise MediaError("symlink_not_allowed")
    if not source.is_file() or source.stat().st_size > MAX_BYTES:
        raise MediaError("media_size_or_path")
    suffix = source.suffix.lower()
    if suffix not in {".mp3", ".m4a", ".flac", ".ogg", ".aac"}:
        yield source
        return
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaError("ffmpeg_required")
    with tempfile.TemporaryDirectory(prefix="decode-", dir=temporary_root) as directory:
        target = Path(directory) / "decoded.wav"
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-f",
                    {
                        ".mp3": "mp3",
                        ".m4a": "mov",
                        ".flac": "flac",
                        ".ogg": "ogg",
                        ".aac": "aac",
                    }[suffix],
                    "-i",
                    str(source.resolve()),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-map_metadata",
                    "-1",
                    "-c:a",
                    "pcm_s16le",
                    "-fs",
                    str(MAX_BYTES),
                    str(target),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300,
                check=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise MediaError("decode_timeout") from exc
        except (subprocess.CalledProcessError, OSError) as exc:
            raise MediaError("decode_failed") from exc
        if target.stat().st_size >= MAX_BYTES:
            raise MediaError("media_size_or_path")
        probe(target)
        yield target
