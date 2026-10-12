"""Durable job queue with two independent lanes and cooperative cancellation.

Lane "models" runs model download/verification; lane "media" runs everything else
(inference, rendering, analysis). Each lane executes one job at a time, so at most
one inference runs at once, but a long model download no longer blocks media work.
A media job never starts while a model operation for the same model is queued or
running, which keeps the old guarantee that "install, then use" runs in order.
"""

from __future__ import annotations

import json
import threading

from .core import Core, now
from .engines.cache import CACHE
from .errors import DomainError
from .waveforms import cached_analysis

LANES = ("models", "media")


class JobRunner:
    def __init__(self, core: Core, models=None):
        self.core = core
        self.models = models
        self.stop = threading.Event()
        self.threads = [
            threading.Thread(
                target=self.run, args=(lane,), name=f"nexus-jobs-{lane}", daemon=True
            )
            for lane in LANES
        ]

    def start(self):
        for thread in self.threads:
            thread.start()

    def close(self):
        self.stop.set()
        for thread in self.threads:
            if thread.is_alive():
                thread.join(timeout=35)
        CACHE.clear()

    def claim_next(self, workflow_id=None, job_id=None, lane=None):
        """Claim one queued task atomically, including across worker connections.

        lane=None considers every job (used by tests and synchronous callers).
        """
        if lane not in (None, *LANES):
            raise ValueError("invalid_lane")
        lane_filter = {
            None: "1=1",
            "models": "child.kind='model_operation'",
            "media": """child.kind<>'model_operation' AND NOT EXISTS(
                SELECT 1 FROM jobs op WHERE op.kind='model_operation'
                AND op.state IN ('queued','running')
                AND json_extract(op.options,'$.model_id')
                    = json_extract(child.options,'$.model_id'))""",
        }[lane]
        with self.core.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Resolve terminal dependency failures before claiming another child.
            while db.execute(
                """UPDATE jobs SET state='cancelled',error='dependency_failed',
                    cancel_requested=1,updated=? WHERE state='queued' AND depends_on IN
                    (SELECT id FROM jobs WHERE state IN ('failed','cancelled','interrupted'))""",
                (now(),),
            ).rowcount:
                pass
            row = db.execute(
                """UPDATE jobs SET state='running',updated=?
                WHERE id=(SELECT child.id FROM jobs child LEFT JOIN jobs parent ON parent.id=child.depends_on
                    WHERE child.state='queued' AND child.cancel_requested=0
                    AND (child.depends_on IS NULL OR parent.state='completed')
                    AND (? IS NULL OR child.workflow_id=?) AND (? IS NULL OR child.id=?)
                    AND """
                + lane_filter
                + """
                    ORDER BY child.created,child.item_index,child.step_index,child.id LIMIT 1)
                AND state='queued' AND cancel_requested=0 RETURNING id""",
                (now(), workflow_id, workflow_id, job_id, job_id),
            ).fetchone()
            if row:
                child = db.execute(
                    "SELECT * FROM jobs WHERE id=?", (row["id"],)
                ).fetchone()
                if child["depends_on"] and not child["asset_id"]:
                    parent = db.execute(
                        "SELECT asset_id,result FROM jobs WHERE id=?",
                        (child["depends_on"],),
                    ).fetchone()
                    result = json.loads(parent["result"]) if parent["result"] else {}
                    asset_id = result.get("asset_id") or parent["asset_id"]
                    asset = db.execute(
                        "SELECT project_id FROM assets WHERE id=?", (asset_id,)
                    ).fetchone()
                    if not asset or asset["project_id"] != child["project_id"]:
                        db.execute(
                            "UPDATE jobs SET state='failed',error='dependency_output_missing' WHERE id=?",
                            (row["id"],),
                        )
                        return None
                    db.execute(
                        "UPDATE jobs SET asset_id=? WHERE id=?", (asset_id, row["id"])
                    )
            return row["id"] if row else None

    def run(self, lane=None):
        while not self.stop.wait(0.1):
            identifier = self.claim_next(lane=lane)
            if identifier:
                self.execute(identifier)

    def execute(self, identifier: str):
        last = -1

        def progress(value):
            nonlocal last
            percent = int(value * 100)
            if percent != last:
                last = percent
                with self.core.db.connect() as db:
                    db.execute(
                        "UPDATE jobs SET progress=?,updated=? WHERE id=?",
                        (value, now(), identifier),
                    )

        def cancelled():
            return self.stop.is_set() or bool(
                self.core.job(identifier)["cancel_requested"]
            )

        try:
            with self.core.job_outputs():
                job = self.core.job(identifier)
                if job["state"] != "running":
                    return
                if cancelled():
                    raise InterruptedError
                options = json.loads(job["options"])
                if job["kind"] == "apply_repair":
                    from .project_repair import apply

                    apply(self.core, job, progress, cancelled)
                    return
                if job["kind"] == "duplicate_project":
                    from .project_copy import execute

                    execute(self.core, job, progress, cancelled)
                    return
                if job["kind"] == "model_operation":
                    from .model_jobs import execute

                    result = execute(
                        self.core, self.models, options, progress, cancelled
                    )
                elif job["kind"] == "plan_repair":
                    from .project_repair import plan

                    result = plan(self.core, job["project_id"], progress, cancelled)
                elif job["kind"] == "validate_project":
                    from .project_check import execute

                    result = execute(self.core, job["project_id"], progress, cancelled)
                elif job["kind"] == "analyze":
                    asset = self.core.asset(job["asset_id"])
                    settings = self.core.db.settings()
                    result = cached_analysis(
                        self.core.db.root,
                        self.core.asset_path(job["asset_id"]),
                        asset["sha256"],
                        progress,
                        cancelled,
                        cache_enabled=settings.get("waveform_cache_enabled", True),
                        max_bytes=settings.get("waveform_cache_mb", 0) * 1048576,
                    )
                elif job["kind"] == "transcribe":
                    from .engines import require_engine

                    adapter = require_engine(
                        self.models.require(options["model_id"])["engine"], "transcribe"
                    )

                    result = adapter.transcribe(
                        self.core.asset_path(job["asset_id"]),
                        self.models.directory(options["model_id"]),
                        options,
                        progress,
                        cancelled,
                    )
                    if cancelled():
                        raise InterruptedError
                    transcript_id = self.core.save_transcript(job, result)
                    result = {
                        k: v
                        for k, v in result.items()
                        if k not in {"segments", "words", "text"}
                    }
                    result["transcript_id"] = transcript_id
                elif job["kind"] in {"audiobook", "dubbing"}:
                    from .production import audiobook, dubbing

                    action = audiobook if job["kind"] == "audiobook" else dubbing
                    result = action(
                        self.core, self.models, job, options, progress, cancelled
                    )
                elif job["kind"] == "timeline":
                    from .timeline import render

                    temporary = self.core.db.root / (identifier + ".wav")
                    try:
                        result = render(
                            options["clips"],
                            self.core,
                            job["project_id"],
                            temporary,
                            progress,
                            cancelled,
                            sample_rate=options.get("sample_rate", 24000),
                            channels=options.get("channels", 1),
                            tracks=options.get("tracks"),
                        )
                        result["asset_id"] = self.core.import_file(
                            job["project_id"], temporary, "Timeline mix.wav"
                        )["id"]
                    finally:
                        temporary.unlink(missing_ok=True)
                elif job["kind"] == "tts":
                    from .engines import require_engine

                    adapter = require_engine(
                        self.models.require(options["model_id"])["engine"], "tts"
                    )

                    temporary = self.core.db.root / (identifier + ".wav")
                    try:
                        result = adapter.synthesize(
                            self.models.directory(options["model_id"]),
                            options,
                            temporary,
                            progress,
                            cancelled,
                        )
                        result["asset_id"] = self.core.import_file(
                            job["project_id"],
                            temporary,
                            "Speech - "
                            + " ".join(options["text"].split())[:80]
                            + ".wav",
                        )["id"]
                    finally:
                        temporary.unlink(missing_ok=True)
                else:
                    raise DomainError("unknown_job_kind")
                with self.core.db.connect() as db:
                    if cancelled():
                        raise InterruptedError
                    completed = db.execute(
                        "UPDATE jobs SET state='completed',progress=1,result=?,updated=? WHERE id=? AND state='running' AND cancel_requested=0",
                        (json.dumps(result), now(), identifier),
                    )
                    if not completed.rowcount:
                        raise InterruptedError
        except InterruptedError:
            state = "interrupted" if self.stop.is_set() else "cancelled"
            with self.core.db.connect() as db:
                db.execute(
                    "UPDATE jobs SET state=?,progress=NULL,updated=? WHERE id=?",
                    (state, now(), identifier),
                )
        except Exception as exc:  # noqa: BLE001 - task boundary must persist unexpected failures
            from .auditlog import job_failed

            job_failed(identifier, self.core.job(identifier)["kind"], exc)
            # Persist a stable, content-free code. Only DomainError codes are safe
            # to expose; any other exception is reported generically.
            code = exc.code if isinstance(exc, DomainError) else "processing_failed"
            with self.core.db.connect() as db:
                db.execute(
                    "UPDATE jobs SET state='failed',error=?,updated=? WHERE id=?",
                    (code, now(), identifier),
                )
