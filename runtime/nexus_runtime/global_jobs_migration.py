"""Permit global model jobs while retaining project ownership for every other kind."""


def migrate(db):
    # Rebuild only jobs. Foreign keys are disabled outside the transaction so
    # replacing its table cannot cascade into transcripts, archives or events.
    db.commit()
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        db.execute("BEGIN IMMEDIATE")
        definitions = [
            row[0]
            for row in db.execute(
                "SELECT sql FROM sqlite_master WHERE tbl_name='jobs' AND type IN ('index','trigger') AND sql IS NOT NULL"
            )
        ]
        db.execute("""CREATE TABLE jobs_v11(
            id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
            asset_id TEXT REFERENCES assets(id) ON DELETE CASCADE,kind TEXT NOT NULL,
            state TEXT NOT NULL,progress REAL,created TEXT NOT NULL,updated TEXT NOT NULL,
            result TEXT,error TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,
            options TEXT NOT NULL DEFAULT '{}',
            workflow_id TEXT REFERENCES workflow_runs(id) ON DELETE CASCADE,
            depends_on TEXT REFERENCES jobs(id) ON DELETE SET NULL,item_index INTEGER,step_index INTEGER,
            CHECK(project_id IS NOT NULL OR kind='model_operation'))""")
        db.execute("INSERT INTO jobs_v11 SELECT * FROM jobs")
        db.execute("DROP TABLE jobs")
        db.execute("ALTER TABLE jobs_v11 RENAME TO jobs")
        for statement in definitions:
            db.execute(statement)
        db.execute("""CREATE UNIQUE INDEX jobs_active_model ON jobs(json_extract(options,'$.model_id'))
            WHERE kind='model_operation' AND state IN ('queued','running')""")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("global_jobs_migration_foreign_key_error")
        db.execute("PRAGMA user_version=11")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")
