"""Local literal search with bounded results and a SQLite execution deadline."""

import sqlite3
import time

from .errors import DomainError


def search(core, query):
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 100:
        raise DomainError("invalid_search_query")
    query = query.strip().casefold()
    active = "p.id NOT IN (SELECT project_id FROM project_trash)"
    visible = active + " AND a.id NOT IN (SELECT asset_id FROM asset_trash)"
    statements = {
        "projects": f"SELECT p.id,p.id AS project_id,p.name AS label FROM projects p WHERE {active} AND instr(nexus_fold(p.name),?)>0 ORDER BY p.modified DESC,p.id LIMIT 21",
        "assets": f"SELECT a.id,a.project_id,a.id AS asset_id,a.name AS label FROM assets a JOIN projects p ON p.id=a.project_id WHERE {visible} AND instr(nexus_fold(a.name),?)>0 ORDER BY a.created DESC,a.id LIMIT 21",
        "transcripts": f"""SELECT t.id,t.project_id,t.asset_id,a.name AS label,
            substr(json_extract(s.value,'$.text'),1,240) AS snippet,
            CAST(s.key AS INTEGER) AS segment
            FROM transcripts t JOIN assets a ON a.id=t.asset_id
            JOIN projects p ON p.id=t.project_id JOIN json_each(t.segments) s
            WHERE {visible} AND instr(nexus_fold(json_extract(s.value,'$.text')),?)>0
            ORDER BY t.updated DESC,t.id,CAST(s.key AS INTEGER) LIMIT 21""",
    }
    groups = {}
    deadline = time.monotonic() + 0.5
    try:
        with core.db.connect() as db:
            db.create_function(
                "nexus_fold", 1, lambda s: (s or "").casefold(), deterministic=True
            )
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            try:
                for kind, sql in statements.items():
                    rows = [dict(row) for row in db.execute(sql, (query,))]
                    groups[kind] = {"items": rows[:20], "more": len(rows) > 20}
            finally:
                db.set_progress_handler(None, 0)
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise DomainError("search_limit_exceeded") from exc
        raise
    return {"groups": groups}
