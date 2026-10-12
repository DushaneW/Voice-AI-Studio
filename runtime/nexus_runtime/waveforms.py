"""Disposable, bounded waveform cache for immutable managed audio."""

import json
import logging
import math
import os
import re
import tempfile
from pathlib import Path

from .errors import DomainError
from .media import analyze

VERSION = 1
MAX_CACHE_BYTES = 65536


def _path(root: Path, digest: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise DomainError("invalid_checksum")
    return root / "cache" / "waveforms" / f"v{VERSION}-{digest}.json"


def safe_directory(root: Path):
    return (
        not (root / "cache").is_symlink()
        and not (root / "cache" / "waveforms").is_symlink()
    )


def prune(root: Path, max_bytes: int):
    if max_bytes <= 0 or not safe_directory(root):
        return
    try:
        files = []
        with os.scandir(root / "cache" / "waveforms") as entries:
            for index, entry in enumerate(entries):
                if index >= 5000:
                    return
                if re.fullmatch(
                    r"v[0-9]+-[0-9a-f]{64}\.json", entry.name
                ) and entry.is_file(follow_symlinks=False):
                    stat = entry.stat(follow_symlinks=False)
                    files.append((stat.st_mtime_ns, stat.st_size, Path(entry.path)))
        total = sum(size for _, size, _ in files)
        for _, size, path in sorted(files):
            if total <= max_bytes:
                break
            path.unlink(missing_ok=True)
            total -= size
    except OSError:
        logging.getLogger(__name__).warning("waveform_cache_prune_failed")


def read(root: Path, digest: str) -> dict | None:
    path = _path(root, digest)
    if not safe_directory(root):
        return None
    try:
        if path.is_symlink():
            return None
        with path.open("rb") as stream:
            raw = stream.read(MAX_CACHE_BYTES + 1)
        if len(raw) > MAX_CACHE_BYTES:
            return None
        data = json.loads(raw)
        if data["version"] != VERSION or data["sha256"] != digest:
            return None
        result = data["result"]
        peaks = result["peaks"]
        if not isinstance(peaks, list) or not 1 <= len(peaks) <= 640:
            return None
        if any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
            for p in peaks
        ):
            return None
        for key in ("peak_dbfs", "rms_dbfs"):
            value = result[key]
            if value is not None and (
                type(value) not in (int, float) or not math.isfinite(value) or value > 0
            ):
                return None
        for key in ("duration", "sample_rate", "channels", "frames", "size"):
            value = result[key]
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                return None
        return {
            key: result[key]
            for key in (
                "peaks",
                "peak_dbfs",
                "rms_dbfs",
                "duration",
                "sample_rate",
                "channels",
                "frames",
                "size",
            )
        }
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return None


def cached_analysis(
    root: Path,
    path: Path,
    digest: str,
    progress,
    cancelled,
    *,
    cache_enabled=True,
    max_bytes=0,
) -> dict:
    if cancelled():
        raise InterruptedError
    result = read(root, digest) if cache_enabled else None
    if result is not None:
        prune(root, max_bytes)
        progress(1.0)
        return result
    result = analyze(path, progress, cancelled)
    if cancelled():
        raise InterruptedError
    if not cache_enabled or not safe_directory(root):
        return result
    destination = _path(root, digest)
    temporary = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(
            {"version": VERSION, "sha256": digest, "result": result}, allow_nan=False
        )
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix="waveform-",
            suffix=".part",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, destination)
        prune(root, max_bytes)
    except OSError:
        # Cache is disposable. A failed cache write must not invalidate real analysis.
        logging.getLogger(__name__).warning("waveform_cache_write_failed")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("waveform_cache_cleanup_failed")
    return result
