"""Durable project duplication: copy bytes first, then publish all metadata atomically."""

import hashlib
import json
import logging
import os
import shutil
import uuid

from . import VERSION
from .core import now
from .errors import DomainError
from .media import MAX_BYTES


def queue(core, project_id, request_id, name):
    core.require_project(project_id)
    identifier = str(uuid.UUID(request_id))
    name = name.strip()
    if not name or len(name) > 120:
        raise DomainError("invalid_name")
    options = json.dumps({"name": name}, sort_keys=True)
    with core.db.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        core.require_project(project_id)
        previous = db.execute(
            "SELECT project_id,kind,options FROM jobs WHERE id=?", (identifier,)
        ).fetchone()
        if previous:
            if (
                previous["project_id"] != project_id
                or previous["kind"] != "duplicate_project"
                or previous["options"] != options
            ):
                raise DomainError("request_id_conflict")
        else:
            stamp = now()
            db.execute(
                "INSERT INTO jobs(id,project_id,kind,state,created,updated,options) VALUES(?,?,'duplicate_project','queued',?,?,?)",
                (identifier, project_id, stamp, stamp, options),
            )
    return core.job(identifier)


def cleanup(core, identifier):
    # Job UUID and ownership in SQLite, never arbitrary paths supplied by a client.
    identifier = str(uuid.UUID(identifier))
    rows = core.db.rows(
        "SELECT state FROM jobs WHERE id=? AND kind='duplicate_project'", (identifier,)
    )
    if not rows or rows[0]["state"] in {"queued", "running"}:
        return
    referenced = {
        r["path"]
        for r in core.db.rows(
            "SELECT path FROM assets WHERE path LIKE ?", (f"copy-{identifier}-%",)
        )
    }
    for path in core.assets.glob(f"copy-{identifier}-*.wav"):
        if path.name not in referenced:
            path.unlink(missing_ok=True)
    staging = core.db.root / f"duplicate-{identifier}"
    if staging.is_symlink():
        staging.unlink()
    elif staging.is_dir():
        shutil.rmtree(staging)


def recover(core):
    for row in core.db.rows(
        "SELECT id FROM jobs WHERE kind='duplicate_project' AND state NOT IN ('queued','running')"
    ):
        try:
            cleanup(core, row["id"])
        except OSError:
            logging.getLogger(__name__).exception("Project copy cleanup failed")


def execute(core, job, progress, cancelled):
    identifier = str(uuid.UUID(job["id"]))
    namespace = uuid.UUID(identifier)
    target = str(uuid.uuid5(namespace, "project"))
    staging = core.db.root / f"duplicate-{identifier}"
    if staging.exists() or staging.is_symlink():
        raise DomainError("copy_staging_exists")
    core.require_project(job["project_id"])
    # One read snapshot; long file copies do not hold a database transaction.
    with core.db.connect() as db:
        db.execute("BEGIN")
        source = dict(
            db.execute(
                "SELECT * FROM projects WHERE id=?", (job["project_id"],)
            ).fetchone()
        )
        assets = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM assets WHERE project_id=?", (source["id"],)
            )
        ]
        transcripts = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM transcripts WHERE project_id=?", (source["id"],)
            )
        ]
        documents = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM documents WHERE project_id=?", (source["id"],)
            )
        ]
        trashed = {
            r[0]
            for r in db.execute(
                "SELECT asset_id FROM asset_trash WHERE asset_id IN (SELECT id FROM assets WHERE project_id=?)",
                (source["id"],),
            )
        }
    mapping = {a["id"]: str(uuid.uuid5(namespace, a["id"])) for a in assets}
    transcript_mapping = {
        tr["id"]: str(uuid.uuid5(namespace, tr["id"])) for tr in transcripts
    }
    total = sum(a["size"] for a in assets)
    completed = 0
    published = []
    committed = False
    staging.mkdir(mode=0o700)
    try:
        for asset in assets:
            if cancelled():
                raise InterruptedError
            path = core.assets / asset["path"]
            if path.is_symlink() or path.resolve().parent != core.assets.resolve():
                raise DomainError("unsafe_asset_path")
            filename = f"copy-{identifier}-{mapping[asset['id']]}.wav"
            digest, size = hashlib.sha256(), 0
            with path.open("rb") as src, (staging / filename).open("xb") as dst:
                while block := src.read(1048576):
                    if cancelled():
                        raise InterruptedError
                    size += len(block)
                    if size > MAX_BYTES or size > asset["size"]:
                        raise DomainError("asset_checksum_mismatch")
                    dst.write(block)
                    digest.update(block)
                    progress(min(0.99, (completed + size) / max(1, total)))
                dst.flush()
                os.fsync(dst.fileno())
            if size != asset["size"] or digest.hexdigest() != asset["sha256"]:
                raise DomainError("asset_checksum_mismatch")
            asset["copy_path"] = filename
            completed += size
        if cancelled():
            raise InterruptedError
        stamp = now()
        with core.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            core.require_project(source["id"])
            state = db.execute(
                "SELECT state,cancel_requested FROM jobs WHERE id=?", (identifier,)
            ).fetchone()
            if (
                not state
                or state["state"] != "running"
                or state["cancel_requested"]
                or cancelled()
            ):
                raise InterruptedError
            db.execute(
                "INSERT INTO projects(id,name,created,modified,favorite,schema_version,application_version) VALUES(?,?,?,?,?,?,?)",
                (
                    target,
                    json.loads(job["options"])["name"],
                    stamp,
                    stamp,
                    source["favorite"],
                    source["schema_version"],
                    VERSION,
                ),
            )
            for asset in assets:
                path = core.assets / asset["copy_path"]
                if path.exists() or path.is_symlink():
                    raise DomainError("copy_target_exists")
                os.replace(staging / asset["copy_path"], path)
                published.append(path)
                db.execute(
                    "INSERT INTO assets(id,project_id,name,path,duration,sample_rate,channels,frames,size,sha256,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        mapping[asset["id"]],
                        target,
                        asset["name"],
                        asset["copy_path"],
                        asset["duration"],
                        asset["sample_rate"],
                        asset["channels"],
                        asset["frames"],
                        asset["size"],
                        asset["sha256"],
                        stamp,
                    ),
                )
            for tr in transcripts:
                db.execute(
                    "INSERT INTO transcripts(id,job_id,project_id,asset_id,segments,language,revision,updated) VALUES(?,NULL,?,?,?,?,1,?)",
                    (
                        transcript_mapping[tr["id"]],
                        target,
                        mapping[tr["asset_id"]],
                        tr["segments"],
                        tr["language"],
                        stamp,
                    ),
                )
            for document in documents:
                content = json.loads(document["content"])
                if document["kind"] == "timeline":
                    for clip in content.get("clips", []):
                        clip["asset_id"] = mapping[clip["asset_id"]]
                if content.get("transcriptId"):
                    content["transcriptId"] = transcript_mapping[
                        content["transcriptId"]
                    ]
                db.execute(
                    "INSERT INTO documents(project_id,kind,content,revision,updated) VALUES(?,?,?,1,?)",
                    (target, document["kind"], json.dumps(content), stamp),
                )
            db.execute(
                "INSERT INTO document_revisions(project_id,kind,revision,content,created) SELECT project_id,kind,revision,content,updated FROM documents WHERE project_id=?",
                (target,),
            )
            for old_id in trashed:
                db.execute(
                    "INSERT INTO asset_trash(asset_id,deleted_at) VALUES(?,?)",
                    (mapping[old_id], stamp),
                )
            db.execute(
                "INSERT INTO history(project_id,action,at) VALUES(?,'duplicated',?)",
                (target, stamp),
            )
            # The new project and successful job appear together, including after a crash.
            db.execute(
                "UPDATE jobs SET state='completed',progress=1,result=?,updated=? WHERE id=?",
                (
                    json.dumps({"project_id": target, "copied_assets": len(assets)}),
                    stamp,
                    identifier,
                ),
            )
        committed = True
    finally:
        if not committed:
            for path in published:
                path.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
