import sqlite3

from nexus_runtime.database import Database
from nexus_runtime.migrations import LATEST, MIGRATIONS


def test_migrations_are_strictly_increasing_and_end_at_latest():
    versions = [version for version, _ in MIGRATIONS]
    assert versions == sorted(set(versions))
    assert versions[0] == 2 and versions[-1] == LATEST


def test_new_database_reaches_latest_and_reopens_unchanged(tmp_path):
    Database(tmp_path)
    path = tmp_path / "nexus.sqlite3"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    Database(tmp_path)  # idempotent second open
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
        assert tables <= {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
    assert {"projects", "jobs", "transcripts", "job_events", "notifications"} <= tables
