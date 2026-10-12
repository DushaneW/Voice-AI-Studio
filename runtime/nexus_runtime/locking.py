"""OS-owned workspace lease, released even when a process crashes."""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def workspace_lock(root: Path):
    """Hold a nonblocking exclusive lock before opening or recovering the database.

    Keep the lock file: unlinking it lets another process lock a different inode.
    Windows locks its first byte; POSIX uses flock on the open file description.
    """
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "runtime.lock").open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            if handle.seek(0, 2) == 0:
                handle.write(b"\0")
            handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("workspace_in_use") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("workspace_in_use") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
