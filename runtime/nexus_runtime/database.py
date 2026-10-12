"""Short-lived SQLite transactions; WAL persistence and explicit schema versioning."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .errors import DomainError
from .migrations import migrate_to_latest


class Database:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "nexus.sqlite3"
        with self.connect() as db:
            migrate_to_latest(db)
            db.execute(
                "UPDATE jobs SET state='interrupted', error='runtime_interrupted', progress=NULL WHERE state='running'"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        except sqlite3.IntegrityError as exc:
            if str(exc) in {"project_in_trash", "asset_in_trash"}:
                raise DomainError(str(exc)) from exc
            raise
        finally:
            db.close()

    def rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def settings(self) -> dict:
        return {
            r["key"]: json.loads(r["value"])
            for r in self.rows("SELECT key,value FROM settings")
        }
