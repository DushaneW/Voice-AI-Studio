"""Model operations use the same durable queue, events and notifications as media."""

import hashlib
import json
import uuid

from .core import now
from .errors import DomainError

ACTIONS = {"install", "resume", "repair", "verify"}


def fingerprint(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()


def create(core, options):
    if options.get("action") not in ACTIONS or not isinstance(
        options.get("model_id"), str
    ):
        raise DomainError("invalid_model_action")
    identifier, stamp = str(uuid.uuid4()), now()
    with core.db.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT id,options FROM jobs WHERE kind='model_operation' AND state IN ('queued','running') AND json_extract(options,'$.model_id')=?",
            (options["model_id"],),
        ).fetchone()
        if existing:
            if json.loads(existing["options"]) != options:
                raise DomainError("model_operation_in_progress")
            identifier = existing["id"]
        else:
            db.execute(
                "INSERT INTO jobs(id,kind,state,created,updated,options) VALUES(?,'model_operation','queued',?,?,?)",
                (identifier, stamp, stamp, json.dumps(options)),
            )
    return core.job(identifier)


def queue(core, models, identifier, action):
    spec = models.require(identifier)
    if action not in ACTIONS:
        raise DomainError("invalid_model_action")
    if action != "verify" and not core.db.settings().get(
        "model_downloads_allowed", True
    ):
        raise DomainError("model_downloads_disabled")
    if action == "verify":
        models.directory(identifier)
    return create(
        core,
        {"model_id": identifier, "action": action, "catalog_hash": fingerprint(spec)},
    )


def cancel(core, models, identifier, pause=False):
    models.require(identifier)
    rows = core.db.rows(
        "SELECT id FROM jobs WHERE kind='model_operation' AND state IN ('queued','running') AND json_extract(options,'$.model_id')=?",
        (identifier,),
    )
    for row in rows:
        core.cancel(row["id"])
    state = next(model["state"] for model in models.list() if model["id"] == identifier)
    if state in {"downloading", "verifying", "paused", "failed"}:
        models.action(identifier, "pause" if pause else "cancel")
    elif not rows:
        raise DomainError("model_not_downloading")
    return {"accepted": True}


def execute(core, models, options, progress, cancelled):
    identifier, action = options["model_id"], options["action"]
    spec = models.require(identifier)
    if fingerprint(spec) != options.get("catalog_hash"):
        raise DomainError("model_catalog_changed")
    if cancelled():
        raise InterruptedError
    models.action(identifier, action)
    thread = models.thread
    while thread.is_alive():
        thread.join(timeout=0.1)
        state = next(model for model in models.list() if model["id"] == identifier)
        if cancelled() and state["state"] in {"downloading", "verifying"}:
            models.action(identifier, "pause")
        if state["state"] == "downloading" and state["size"]:
            # Bytes actually downloaded, capped below completion while checksum
            # verification and final publication are still pending.
            progress(min(0.99, state["downloaded"] / state["size"]))
    state = next(model for model in models.list() if model["id"] == identifier)
    if cancelled() or state["state"] in {"paused", "cancelled"}:
        raise InterruptedError
    if state["state"] != "installed":
        raise DomainError(state["error"] or "model_download_failed")
    return {
        "model_id": identifier,
        "action": action,
        "bytes": state["size"],
        "verified": True,
    }
