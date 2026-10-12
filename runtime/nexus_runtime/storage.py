"""Bounded storage inventory and explicit disposal of generated waveform cache."""

import os
import re
import shutil
import stat
from pathlib import Path

from .errors import DomainError

LIMIT = 5000


def measure(directory: Path) -> dict:
    result = {"bytes": 0, "files": 0, "complete": True}
    pending = [(directory, 0)]
    visited = 0
    while pending:
        folder, depth = pending.pop()
        if folder.is_symlink():
            result["complete"] = False
            continue
        if not folder.exists():
            continue
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    visited += 1
                    if visited > LIMIT:
                        result["complete"] = False
                        return result
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISREG(info.st_mode):
                        result["bytes"] += info.st_size
                        result["files"] += 1
                    elif stat.S_ISDIR(info.st_mode) and depth < 16:
                        pending.append((Path(entry.path), depth + 1))
                    else:
                        result["complete"] = False
        except OSError:
            result["complete"] = False
    return result


def inventory(core) -> dict:
    root = core.db.root
    categories = {
        name: measure(root / name)
        for name in ("assets", "models", "cache", "backups", "logs")
    }
    database_bytes = 0
    for name in ("nexus.sqlite3", "nexus.sqlite3-wal", "nexus.sqlite3-shm"):
        path = root / name
        try:
            if not path.is_symlink():
                database_bytes += path.stat().st_size
        except FileNotFoundError:
            pass
    usage = shutil.disk_usage(root)
    return {
        "categories": categories,
        "database_bytes": database_bytes,
        "disk_free": usage.free,
        "disk_total": usage.total,
        "trash_audio_bytes": core.db.rows("""SELECT COALESCE(SUM(size),0) AS bytes FROM assets
                WHERE id IN (SELECT asset_id FROM asset_trash)
                OR project_id IN (SELECT project_id FROM project_trash)""")[0]["bytes"],
    }


def clear_waveforms(root: Path) -> dict:
    folder = root / "cache" / "waveforms"
    if (root / "cache").is_symlink() or folder.is_symlink():
        raise DomainError("unsafe_cache_path")
    result = {"removed": 0, "bytes": 0, "complete": True}
    if not folder.exists():
        return result
    with os.scandir(folder) as entries:
        for index, entry in enumerate(entries):
            if index >= LIMIT:
                result["complete"] = False
                break
            if not re.fullmatch(r"v[0-9]+-[0-9a-f]{64}\.json", entry.name):
                continue
            try:
                info = entry.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    continue
                os.unlink(entry.path)
                result["removed"] += 1
                result["bytes"] += info.st_size
            except FileNotFoundError:
                continue
            except OSError:
                result["complete"] = False
    return result
