"""Reviewable revision repair; apply checks hashes and commits all changes atomically."""

import hashlib
import json

from .core import now
from .errors import DomainError
from .validation import validate_document, validate_segments

LIMIT = 50
HISTORY_LIMIT = 100


def digest(row, category):
    fields = (
        [row["content"]]
        if category == "document"
        else [row["segments"], row["language"]]
    )
    return hashlib.sha256(json.dumps(fields).encode()).hexdigest()


def validate(core, project, row, category):
    if category == "document":
        validate_document(core, project, row["kind"], json.loads(row["content"]))
    else:
        validate_segments(
            json.loads(row["segments"]), core.asset(row["asset_id"])["duration"]
        )


def plan(core, project, progress, cancelled):
    core.require_project(project)
    actions, unresolved = [], []
    checked = repairable = unresolved_count = 0
    # Stream every record from one WAL snapshot; do not load a project's large
    # transcripts or all historical revisions into memory at once.
    with core.db.connect() as db:
        db.execute("BEGIN")
        transcript_filter = (
            "project_id=? AND asset_id NOT IN (SELECT asset_id FROM asset_trash)"
        )
        total = db.execute(
            "SELECT count(*) FROM documents WHERE project_id=?", (project,)
        ).fetchone()[0]
        total += db.execute(
            f"SELECT count(*) FROM transcripts WHERE {transcript_filter}", (project,)
        ).fetchone()[0]

        def records():
            for row in db.execute(
                "SELECT * FROM documents WHERE project_id=? ORDER BY kind", (project,)
            ):
                yield "document", dict(row)
            for row in db.execute(
                f"SELECT * FROM transcripts WHERE {transcript_filter} ORDER BY id",
                (project,),
            ):
                yield "transcript", dict(row)

        for category, current in records():
            if cancelled():
                raise InterruptedError
            identifier = current["kind"] if category == "document" else current["id"]
            try:
                validate(core, project, current, category)
            except (ValueError, TypeError, KeyError):
                if category == "document":
                    snapshots = db.execute(
                        "SELECT * FROM document_revisions WHERE project_id=? AND kind=? ORDER BY revision DESC LIMIT ?",
                        (project, identifier, HISTORY_LIMIT),
                    )
                else:
                    snapshots = db.execute(
                        "SELECT * FROM transcript_revisions WHERE transcript_id=? ORDER BY revision DESC LIMIT ?",
                        (identifier, HISTORY_LIMIT),
                    )
                candidate = None
                for snapshot in snapshots:
                    if cancelled():
                        raise InterruptedError
                    try:
                        validate(core, project, {**current, **dict(snapshot)}, category)
                        candidate = dict(snapshot)
                        break
                    except (ValueError, TypeError, KeyError):
                        continue
                if candidate is None:
                    unresolved_count += 1
                    if len(unresolved) < LIMIT:
                        unresolved.append(
                            {
                                "category": category,
                                "id": identifier,
                                "reason": "no_valid_revision_in_window",
                            }
                        )
                else:
                    repairable += 1
                    if len(actions) < LIMIT:
                        actions.append(
                            {
                                "category": category,
                                "id": identifier,
                                "expected_revision": current["revision"],
                                "expected_hash": digest(current, category),
                                "source_revision": candidate["revision"],
                                "source_hash": digest(candidate, category),
                            }
                        )
            checked += 1
            progress(checked / max(1, total))
    return {
        "actions": actions,
        "unresolved": unresolved,
        "limited": repairable > len(actions) or unresolved_count > len(unresolved),
        "repairable_count": repairable,
        "unresolved_count": unresolved_count,
        "remaining_repairs": repairable - len(actions),
        "omitted_findings": unresolved_count - len(unresolved),
        "history_limit": HISTORY_LIMIT,
        "checked": checked,
    }


def queue_apply(core, plan_id):
    job = core.job(plan_id)
    if (
        job["kind"] != "plan_repair"
        or job["state"] != "completed"
        or not job["result"]["actions"]
    ):
        raise DomainError("repair_plan_unavailable")
    return core.create_tts_job(job["project_id"], {"plan_id": plan_id}, "apply_repair")


def apply(core, job, progress, cancelled):
    previous = core.job(json.loads(job["options"])["plan_id"])
    if (
        previous["kind"] != "plan_repair"
        or previous["state"] != "completed"
        or previous["project_id"] != job["project_id"]
    ):
        raise DomainError("repair_plan_unavailable")
    actions = previous["result"]["actions"]
    if not actions or len(actions) > LIMIT + 4:
        raise DomainError("repair_plan_unavailable")
    progress(0)
    with core.db.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        core.require_project(job["project_id"])
        staged = []
        for action in actions:
            if cancelled():
                raise InterruptedError
            category, identifier = action["category"], action["id"]
            if category == "document":
                current = db.execute(
                    "SELECT * FROM documents WHERE project_id=? AND kind=?",
                    (job["project_id"], identifier),
                ).fetchone()
                snapshot = db.execute(
                    "SELECT * FROM document_revisions WHERE project_id=? AND kind=? AND revision=?",
                    (job["project_id"], identifier, action["source_revision"]),
                ).fetchone()
            elif category == "transcript":
                current = db.execute(
                    "SELECT * FROM transcripts WHERE project_id=? AND id=?",
                    (job["project_id"], identifier),
                ).fetchone()
                snapshot = db.execute(
                    "SELECT * FROM transcript_revisions WHERE transcript_id=? AND revision=?",
                    (identifier, action["source_revision"]),
                ).fetchone()
            else:
                raise DomainError("repair_plan_unavailable")
            if (
                not current
                or not snapshot
                or current["revision"] != action["expected_revision"]
                or digest(current, category) != action["expected_hash"]
                or digest(snapshot, category) != action["source_hash"]
            ):
                raise DomainError("repair_plan_stale")
            validate(
                core, job["project_id"], {**dict(current), **dict(snapshot)}, category
            )
            staged.append(
                (category, identifier, dict(snapshot), current["revision"] + 1)
            )
        stamp = now()
        for category, identifier, snapshot, revision in staged:
            if cancelled():
                raise InterruptedError
            if category == "document":
                db.execute(
                    "UPDATE documents SET content=?,revision=?,updated=? WHERE project_id=? AND kind=?",
                    (
                        snapshot["content"],
                        revision,
                        stamp,
                        job["project_id"],
                        identifier,
                    ),
                )
                db.execute(
                    "INSERT INTO document_revisions(project_id,kind,revision,content,created) VALUES(?,?,?,?,?)",
                    (
                        job["project_id"],
                        identifier,
                        revision,
                        snapshot["content"],
                        stamp,
                    ),
                )
            else:
                db.execute(
                    "UPDATE transcripts SET segments=?,language=?,revision=?,updated=? WHERE id=?",
                    (
                        snapshot["segments"],
                        snapshot["language"],
                        revision,
                        stamp,
                        identifier,
                    ),
                )
        if cancelled():
            raise InterruptedError
        db.execute(
            "UPDATE projects SET modified=? WHERE id=?", (stamp, job["project_id"])
        )
        changed = db.execute(
            "UPDATE jobs SET state='completed',progress=1,result=?,updated=? WHERE id=? AND state='running' AND cancel_requested=0",
            (
                json.dumps({"restored": len(staged), "plan_id": previous["id"]}),
                stamp,
                job["id"],
            ),
        )
        if not changed.rowcount:
            raise InterruptedError
