"""Ordered schema migrations.

Each step brings the database from the previous version to `version` and must set
`PRAGMA user_version` itself inside its own transaction. Never edit a released
step; append a new one and raise LATEST.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

INITIAL_SCHEMA = """
CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL,
 modified TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0, schema_version INTEGER NOT NULL DEFAULT 1,
 application_version TEXT NOT NULL DEFAULT '0.1.0');
CREATE TABLE assets(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 name TEXT NOT NULL, path TEXT NOT NULL, duration REAL NOT NULL, sample_rate INTEGER NOT NULL,
 channels INTEGER NOT NULL, frames INTEGER NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE jobs(id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, state TEXT NOT NULL, progress REAL, created TEXT NOT NULL, updated TEXT NOT NULL,
 result TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE history(id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 action TEXT NOT NULL, at TEXT NOT NULL);
PRAGMA user_version=1;
"""

STEP_2 = """BEGIN IMMEDIATE;
                CREATE TABLE jobs_v2(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,kind TEXT NOT NULL,state TEXT NOT NULL,progress REAL,
                created TEXT NOT NULL,updated TEXT NOT NULL,result TEXT,error TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,
                options TEXT NOT NULL DEFAULT '{}');
                INSERT INTO jobs_v2 SELECT *, '{}' FROM jobs;
                DROP TABLE jobs;
                ALTER TABLE jobs_v2 RENAME TO jobs;
                CREATE TABLE transcripts(id TEXT PRIMARY KEY,job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                segments TEXT NOT NULL,language TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated TEXT NOT NULL);
                PRAGMA user_version=2;
                COMMIT;"""

STEP_3 = """BEGIN IMMEDIATE;
                CREATE TABLE documents(project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                kind TEXT NOT NULL,content TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,updated TEXT NOT NULL,
                PRIMARY KEY(project_id,kind));
                PRAGMA user_version=3; COMMIT;"""

STEP_4 = """BEGIN IMMEDIATE;
                CREATE TABLE workflow_templates(
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                    definition TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE workflow_runs(
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    template_id TEXT NOT NULL, template_snapshot TEXT NOT NULL,
                    inputs TEXT NOT NULL, request_key TEXT NOT NULL UNIQUE,
                    request_hash TEXT NOT NULL, created TEXT NOT NULL);
                ALTER TABLE jobs ADD COLUMN workflow_id TEXT REFERENCES workflow_runs(id) ON DELETE CASCADE;
                ALTER TABLE jobs ADD COLUMN depends_on TEXT REFERENCES jobs(id) ON DELETE SET NULL;
                ALTER TABLE jobs ADD COLUMN item_index INTEGER;
                ALTER TABLE jobs ADD COLUMN step_index INTEGER;
                CREATE INDEX jobs_workflow ON jobs(workflow_id,item_index,step_index);
                CREATE INDEX jobs_queue ON jobs(state,created,id);
                CREATE INDEX jobs_dependency ON jobs(depends_on);
                CREATE INDEX workflow_runs_project ON workflow_runs(project_id,created);
                PRAGMA user_version=4; COMMIT;"""

STEP_5 = """BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS models(id TEXT PRIMARY KEY,state TEXT NOT NULL,
                    downloaded INTEGER NOT NULL DEFAULT 0,error TEXT);
                CREATE TABLE document_revisions(
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,revision INTEGER NOT NULL,content TEXT NOT NULL,
                    created TEXT NOT NULL,PRIMARY KEY(project_id,kind,revision));
                INSERT INTO document_revisions(project_id,kind,revision,content,created)
                    SELECT project_id,kind,revision,content,updated FROM documents;
                PRAGMA user_version=5; COMMIT;"""

STEP_6 = """BEGIN IMMEDIATE;
                CREATE TABLE project_trash(project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,deleted_at TEXT NOT NULL);
                CREATE TABLE asset_trash(asset_id TEXT PRIMARY KEY REFERENCES assets(id) ON DELETE CASCADE,deleted_at TEXT NOT NULL);
                CREATE TRIGGER jobs_active_project BEFORE INSERT ON jobs
                WHEN EXISTS(SELECT 1 FROM project_trash WHERE project_id=NEW.project_id)
                BEGIN SELECT RAISE(ABORT,'project_in_trash'); END;
                CREATE TRIGGER jobs_active_asset BEFORE INSERT ON jobs
                WHEN EXISTS(SELECT 1 FROM asset_trash WHERE asset_id=NEW.asset_id)
                BEGIN SELECT RAISE(ABORT,'asset_in_trash'); END;
                CREATE TRIGGER assets_active_project BEFORE INSERT ON assets
                WHEN EXISTS(SELECT 1 FROM project_trash WHERE project_id=NEW.project_id)
                BEGIN SELECT RAISE(ABORT,'project_in_trash'); END;
                CREATE TRIGGER documents_active_insert BEFORE INSERT ON documents
                WHEN EXISTS(SELECT 1 FROM project_trash WHERE project_id=NEW.project_id)
                BEGIN SELECT RAISE(ABORT,'project_in_trash'); END;
                CREATE TRIGGER documents_active_update BEFORE UPDATE ON documents
                WHEN EXISTS(SELECT 1 FROM project_trash WHERE project_id=NEW.project_id)
                BEGIN SELECT RAISE(ABORT,'project_in_trash'); END;
                PRAGMA user_version=6; COMMIT;"""

STEP_7 = """BEGIN IMMEDIATE;
                CREATE TABLE job_archive(job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,archived_at TEXT NOT NULL);
                PRAGMA user_version=7; COMMIT;"""

STEP_8 = """BEGIN IMMEDIATE;
                CREATE TABLE transcript_revisions(
                    transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL,segments TEXT NOT NULL,language TEXT NOT NULL,
                    created TEXT NOT NULL,PRIMARY KEY(transcript_id,revision));
                INSERT INTO transcript_revisions SELECT id,revision,segments,language,updated FROM transcripts;
                CREATE TRIGGER transcript_snapshot_insert AFTER INSERT ON transcripts
                BEGIN INSERT INTO transcript_revisions VALUES(NEW.id,NEW.revision,NEW.segments,NEW.language,NEW.updated); END;
                CREATE TRIGGER transcript_snapshot_update AFTER UPDATE OF revision ON transcripts
                WHEN NEW.revision != OLD.revision
                BEGIN INSERT INTO transcript_revisions VALUES(NEW.id,NEW.revision,NEW.segments,NEW.language,NEW.updated); END;
                PRAGMA user_version=8; COMMIT;"""

STEP_9 = """BEGIN IMMEDIATE;
                CREATE TABLE import_receipts(
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    request_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
                    sha256 TEXT NOT NULL,
                    PRIMARY KEY(project_id,request_id));
                PRAGMA user_version=9; COMMIT;"""

STEP_10 = """BEGIN IMMEDIATE;
                CREATE TABLE job_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    state TEXT NOT NULL,error TEXT,created TEXT NOT NULL);
                CREATE INDEX job_events_job ON job_events(job_id,id);
                CREATE TABLE notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    state TEXT NOT NULL,created TEXT NOT NULL,read INTEGER NOT NULL DEFAULT 0 CHECK(read IN (0,1)));
                CREATE INDEX notifications_unread ON notifications(read,id);
                CREATE TRIGGER job_event_insert AFTER INSERT ON jobs
                BEGIN INSERT INTO job_events(job_id,state,error,created) VALUES(NEW.id,NEW.state,NEW.error,NEW.created); END;
                CREATE TRIGGER job_event_update AFTER UPDATE OF state ON jobs WHEN NEW.state != OLD.state
                BEGIN INSERT INTO job_events(job_id,state,error,created) VALUES(NEW.id,NEW.state,NEW.error,strftime('%Y-%m-%dT%H:%M:%fZ','now')); END;
                CREATE TRIGGER job_notification AFTER UPDATE OF state ON jobs
                WHEN NEW.state != OLD.state AND NEW.state IN ('completed','failed','cancelled','interrupted')
                BEGIN INSERT INTO notifications(job_id,state,created) VALUES(NEW.id,NEW.state,strftime('%Y-%m-%dT%H:%M:%fZ','now')); END;
                PRAGMA user_version=10; COMMIT;"""


def _step_11(db: sqlite3.Connection) -> None:
    from .global_jobs_migration import migrate

    migrate(db)


def _script(sql: str) -> Callable[[sqlite3.Connection], None]:
    return lambda db: db.executescript(sql)


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (2, _script(STEP_2)),
    (3, _script(STEP_3)),
    (4, _script(STEP_4)),
    (5, _script(STEP_5)),
    (6, _script(STEP_6)),
    (7, _script(STEP_7)),
    (8, _script(STEP_8)),
    (9, _script(STEP_9)),
    (10, _script(STEP_10)),
    (11, _step_11),
]
LATEST = MIGRATIONS[-1][0]


def migrate_to_latest(db: sqlite3.Connection) -> None:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > LATEST:
        raise RuntimeError("Database requires a newer NEXUS version")
    if version == 0:
        db.executescript("BEGIN IMMEDIATE;\n" + INITIAL_SCHEMA + "\nCOMMIT;")
    for target, step in MIGRATIONS:
        if version < target:
            step(db)
