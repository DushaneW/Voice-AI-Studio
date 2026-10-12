"""Bounded, persisted notifications and content-free job transition history."""

from .core import NotFound

VISIBLE = "(j.project_id IS NULL OR j.project_id NOT IN (SELECT project_id FROM project_trash)) AND (j.asset_id IS NULL OR j.asset_id NOT IN (SELECT asset_id FROM asset_trash))"


def search(core, before=None, unread_only=False):
    with core.db.connect() as db:
        db.execute("BEGIN")
        rows = [
            dict(r)
            for r in db.execute(
                f"SELECT n.*,j.kind,j.project_id FROM notifications n JOIN jobs j ON j.id=n.job_id WHERE {VISIBLE} AND (? IS NULL OR n.id<?) AND (?=0 OR n.read=0) ORDER BY n.id DESC LIMIT 51",
                (before, before, int(unread_only)),
            )
        ]
        unread = db.execute(
            f"SELECT count(*) FROM notifications n JOIN jobs j ON j.id=n.job_id WHERE {VISIBLE} AND n.read=0"
        ).fetchone()[0]
    return {
        "items": rows[:50],
        "next_cursor": rows[49]["id"] if len(rows) > 50 else None,
        "unread": unread,
    }


def mark_read(core, identifier):
    if not 0 < identifier <= 9223372036854775807:
        raise NotFound("notification_not_found")
    with core.db.connect() as db:
        changed = db.execute(
            f"UPDATE notifications SET read=1 WHERE id=? AND job_id IN (SELECT j.id FROM jobs j WHERE {VISIBLE})",
            (identifier,),
        )
        if not changed.rowcount:
            raise NotFound("notification_not_found")
    return {"read": True}


def events(core, identifier, before=None):
    with core.db.connect() as db:
        db.execute("BEGIN")
        job = db.execute(
            f"SELECT j.id,j.kind,j.state,j.error,j.progress,j.created,j.updated FROM jobs j WHERE j.id=? AND {VISIBLE}",
            (identifier,),
        ).fetchone()
        if not job:
            raise NotFound("job_not_found")
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT id,state,error,created FROM job_events WHERE job_id=? AND (? IS NULL OR id<?) ORDER BY id DESC LIMIT 101",
                (identifier, before, before),
            )
        ]
    return {
        "job": dict(job),
        "items": rows[:100],
        "next_cursor": rows[99]["id"] if len(rows) > 100 else None,
    }
