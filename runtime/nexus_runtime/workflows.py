"""Declarative, bounded audio pipelines sharing the durable desktop job queue.

Definitions contain data only: no shell commands, Python expressions or URLs.
Every run freezes the definition and atomically enqueues all of its child jobs.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .core import NotFound, now
from .engines import registry
from .errors import DomainError


class TTSOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = "kokoro-v1"
    voice: str = Field(default="af_heart", pattern="^[a-z][a-z]_[a-z0-9_]+$")
    language: str = Field(
        default="en-us", pattern="^(en-us|en-gb|fr-fr|ja|zh|es|hi|it|pt-br)$"
    )
    speed: float = Field(default=1, ge=0.5, le=2, allow_inf_nan=False)


class ASROptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str = "whisper-tiny"
    language: str | None = Field(default=None, pattern="^[a-z]{2,3}$")
    device: str = Field(default="cpu", pattern="^(cpu|cuda)$")


BUILTINS = [
    {
        "id": "audio-review",
        "name": "Audio review",
        "description": "Measure waveform, peak and RMS for a batch of recordings.",
        "definition": {
            "input_kind": "audio",
            "steps": [{"kind": "analyze", "options": {}}],
        },
    },
    {
        "id": "batch-transcription",
        "name": "Recording to transcript",
        "description": "Analyze each recording, then create an editable local transcript.",
        "definition": {
            "input_kind": "audio",
            "steps": [
                {"kind": "analyze", "options": {}},
                {"kind": "transcribe", "options": {}},
            ],
        },
    },
    {
        "id": "voice-publish",
        "name": "Text to reviewed voice",
        "description": "Synthesize each text, then measure the generated audio.",
        "definition": {
            "input_kind": "text",
            "steps": [
                {"kind": "tts", "options": {}},
                {"kind": "analyze", "options": {}},
            ],
        },
    },
    {
        "id": "voice-transcript",
        "name": "Voice and transcript",
        "description": "Generate speech, measure it and transcribe the resulting audio.",
        "definition": {
            "input_kind": "text",
            "steps": [
                {"kind": "tts", "options": {}},
                {"kind": "analyze", "options": {}},
                {"kind": "transcribe", "options": {}},
            ],
        },
    },
]


def validate_definition(value):
    if not isinstance(value, dict) or set(value) != {"input_kind", "steps"}:
        raise DomainError("invalid_workflow_definition")
    if value["input_kind"] not in {"text", "audio"}:
        raise DomainError("invalid_workflow_definition")
    steps = value["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 4:
        raise DomainError("workflow_step_limit")
    current = value["input_kind"]
    clean = []
    for step in steps:
        if not isinstance(step, dict) or set(step) - {"kind", "options"}:
            raise DomainError("invalid_workflow_step")
        kind, options = step.get("kind"), step.get("options", {})
        if not isinstance(options, dict):
            raise DomainError("invalid_workflow_options")
        try:
            if kind == "tts" and current == "text":
                options = TTSOptions.model_validate(options).model_dump()
                current = "audio"
            elif kind == "analyze" and current == "audio" and not options:
                pass
            elif kind == "transcribe" and current == "audio":
                options = ASROptions.model_validate(options).model_dump()
                current = "transcript"
            else:
                raise DomainError("invalid_workflow_step_order")
        except ValidationError as exc:
            raise DomainError("invalid_workflow_options") from exc
        clean.append({"kind": kind, "options": options})
    return {"input_kind": value["input_kind"], "steps": clean}


class WorkflowService:
    def __init__(self, core, models):
        self.core = core
        self.models = models

    def templates(self):
        result = [
            {**t, "builtin": True, "definition": validate_definition(t["definition"])}
            for t in BUILTINS
        ]
        for row in self.core.db.rows(
            "SELECT * FROM workflow_templates ORDER BY created DESC"
        ):
            result.append(
                {**row, "builtin": False, "definition": json.loads(row["definition"])}
            )
        engines = {e["id"]: e for e in registry()}
        for template in result:
            requirements = []
            for step in template["definition"]["steps"]:
                model_id = step["options"].get("model_id")
                if not model_id or any(r["model_id"] == model_id for r in requirements):
                    continue
                model = next(
                    (m for m in self.models.list() if m["id"] == model_id), None
                )
                engine = engines.get(model["engine"]) if model else None
                requirements.append(
                    {
                        "model_id": model_id,
                        "model_installed": bool(
                            model and model["state"] == "installed"
                        ),
                        "engine_installed": bool(engine and engine["installed"]),
                    }
                )
            template["requirements"] = requirements
            template["ready"] = all(
                r["model_installed"] and r["engine_installed"] for r in requirements
            )
        return result

    def template(self, identifier):
        for template in self.templates():
            if template["id"] == identifier:
                return template
        raise NotFound("workflow_template_not_found")

    def create_template(self, name, description, definition):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
            raise DomainError("invalid_name")
        if not isinstance(description, str) or len(description) > 500:
            raise DomainError("invalid_workflow_description")
        definition = validate_definition(definition)
        self.validate_requirements(definition, installed=False)
        identifier = "custom-" + str(uuid.uuid4())
        with self.core.db.connect() as db:
            db.execute(
                "INSERT INTO workflow_templates VALUES(?,?,?,?,?)",
                (identifier, name.strip(), description, json.dumps(definition), now()),
            )
        return self.template(identifier)

    def delete_template(self, identifier):
        if any(t["id"] == identifier for t in BUILTINS):
            raise DomainError("builtin_template_readonly")
        with self.core.db.connect() as db:
            if not db.execute(
                "DELETE FROM workflow_templates WHERE id=?", (identifier,)
            ).rowcount:
                raise NotFound("workflow_template_not_found")

    def validate_requirements(self, definition, installed=True):
        from .engines import require_engine

        for step in definition["steps"]:
            if step["kind"] == "analyze":
                continue
            model_id = step["options"]["model_id"]
            model = self.models.require(model_id)
            require_engine(model["engine"], step["kind"])
            if installed:
                self.models.directory(model_id)
                descriptor = next(e for e in registry() if e["id"] == model["engine"])
                if not descriptor["installed"]:
                    raise DomainError("engine_not_installed")

    def start(self, project_id, template_id, inputs, request_key, *, snapshot=None):
        if not isinstance(request_key, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{8,100}", request_key
        ):
            raise DomainError("invalid_request_key")
        if not isinstance(inputs, list) or not 1 <= len(inputs) <= 64:
            raise DomainError("workflow_input_limit")
        if any(
            not isinstance(value, str) or not value.strip() or len(value) > 5000
            for value in inputs
        ):
            raise DomainError("invalid_workflow_input")
        encoded = json.dumps(
            {
                "project_id": project_id,
                "template_id": template_id,
                "inputs": inputs,
                "snapshot": snapshot,
            },
            sort_keys=True,
            allow_nan=False,
        )
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        existing = self.core.db.rows(
            "SELECT id,request_hash FROM workflow_runs WHERE request_key=?",
            (request_key,),
        )
        if existing:
            if existing[0]["request_hash"] != fingerprint:
                raise DomainError("workflow_request_conflict")
            return self.run(existing[0]["id"])
        self.core.require_project(project_id)
        template = snapshot or self.template(template_id)
        definition = validate_definition(template["definition"])
        self.validate_requirements(definition)
        if definition["input_kind"] == "audio":
            if len(inputs) != len(set(inputs)):
                raise DomainError("duplicate_workflow_input")
            for identifier in inputs:
                if self.core.asset(identifier)["project_id"] != project_id:
                    raise DomainError("asset_project_mismatch")
        snapshot = {
            "id": template_id,
            "name": template["name"],
            "definition": definition,
        }
        run_id, stamp = str(uuid.uuid4()), now()
        with self.core.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT id,request_hash FROM workflow_runs WHERE request_key=?",
                (request_key,),
            ).fetchone()
            if existing:
                if existing["request_hash"] != fingerprint:
                    raise DomainError("workflow_request_conflict")
                run_id = existing["id"]
            else:
                db.execute(
                    "INSERT INTO workflow_runs VALUES(?,?,?,?,?,?,?,?)",
                    (
                        run_id,
                        project_id,
                        template_id,
                        json.dumps(snapshot),
                        json.dumps(inputs),
                        request_key,
                        fingerprint,
                        stamp,
                    ),
                )
                for item_index, value in enumerate(inputs):
                    parent = None
                    for step_index, step in enumerate(definition["steps"]):
                        job_id = str(uuid.uuid4())
                        options = dict(step["options"])
                        asset_id = (
                            value if definition["input_kind"] == "audio" else None
                        )
                        if step["kind"] == "tts":
                            options.update(text=value, project_id=project_id)
                        db.execute(
                            """INSERT INTO jobs(id,project_id,asset_id,kind,state,created,updated,options,
                                   workflow_id,depends_on,item_index,step_index) VALUES(?,?,?,?,'queued',?,?,?,?,?,?,?)""",
                            (
                                job_id,
                                project_id,
                                asset_id,
                                step["kind"],
                                stamp,
                                stamp,
                                json.dumps(options),
                                run_id,
                                parent,
                                item_index,
                                step_index,
                            ),
                        )
                        parent = job_id
        return self.run(run_id)

    def run(self, identifier):
        rows = self.core.db.rows(
            "SELECT * FROM workflow_runs WHERE id=?", (identifier,)
        )
        if not rows:
            raise NotFound("workflow_not_found")
        row = rows[0]
        snapshot = json.loads(row["template_snapshot"])
        jobs = self.core.db.rows(
            "SELECT id,kind,state,progress,error,asset_id,depends_on,item_index,step_index,created,updated FROM jobs WHERE workflow_id=? ORDER BY item_index,step_index",
            (identifier,),
        )
        states = [job["state"] for job in jobs]
        active = any(s in {"queued", "running"} for s in states)
        state = (
            ("running" if any(s != "queued" for s in states) else "queued")
            if active
            else (
                "failed"
                if "failed" in states
                else "interrupted"
                if "interrupted" in states
                else "cancelled"
                if "cancelled" in states
                else "completed"
            )
        )
        complete = states.count("completed")
        done = sum(s not in {"queued", "running"} for s in states)
        return {
            "id": identifier,
            "project_id": row["project_id"],
            "template_id": row["template_id"],
            "name": snapshot["name"],
            "created": row["created"],
            "state": state,
            "completed": complete,
            "finished": done,
            "total": len(jobs),
            "progress": (
                done + sum(j["progress"] or 0 for j in jobs if j["state"] == "running")
            )
            / max(1, len(jobs)),
            "jobs": jobs,
            "definition": snapshot["definition"],
        }

    def list_runs(self, project_id, before=None):
        self.core.require_project(project_id)
        if before:
            cursor = self.core.db.rows(
                "SELECT created FROM workflow_runs WHERE id=? AND project_id=?",
                (before, project_id),
            )
            if not cursor:
                raise DomainError("invalid_workflow_cursor")
            stamp = cursor[0]["created"]
            rows = self.core.db.rows(
                "SELECT id FROM workflow_runs WHERE project_id=? AND (created<? OR (created=? AND id<?)) ORDER BY created DESC,id DESC LIMIT 51",
                (project_id, stamp, stamp, before),
            )
        else:
            rows = self.core.db.rows(
                "SELECT id FROM workflow_runs WHERE project_id=? ORDER BY created DESC,id DESC LIMIT 51",
                (project_id,),
            )
        items = [
            {
                k: v
                for k, v in self.run(r["id"]).items()
                if k not in {"jobs", "definition"}
            }
            for r in rows[:50]
        ]
        return {
            "items": items,
            "next_cursor": rows[49]["id"] if len(rows) > 50 else None,
        }

    def cancel(self, identifier):
        self.run(identifier)
        with self.core.db.connect() as db:
            db.execute(
                """UPDATE jobs SET cancel_requested=1,updated=?,
                state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END
                WHERE workflow_id=? AND state IN ('queued','running')""",
                (now(), identifier),
            )
        return self.run(identifier)

    def retry(self, identifier, request_key):
        run = self.run(identifier)
        if run["state"] not in {"failed", "cancelled", "interrupted"}:
            raise DomainError("workflow_not_retryable")
        row = self.core.db.rows(
            "SELECT * FROM workflow_runs WHERE id=?", (identifier,)
        )[0]
        return self.start(
            row["project_id"],
            row["template_id"],
            json.loads(row["inputs"]),
            request_key,
            snapshot=json.loads(row["template_snapshot"]),
        )
