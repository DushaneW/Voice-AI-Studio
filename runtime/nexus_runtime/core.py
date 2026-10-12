"""Application operations shared by desktop IPC, API and tests."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path

from . import VERSION
from .database import Database
from .errors import DomainError, NotFound
from .media import MediaError, checksum, probe
from .validation import merge_transcript_edit, validate_document, validate_segments


def now() -> str:
    return datetime.now(UTC).isoformat()


_outputs = ContextVar("nexus_job_outputs", default=None)


class Core:
    def __init__(self, root: Path):
        self.db = Database(root)
        self.assets = self.db.root / "assets"
        self.assets.mkdir(exist_ok=True, mode=0o700)
        from .project_copy import recover

        recover(self)

    @contextmanager
    def job_outputs(self):
        """Rollback only this worker's generated records on failure/cancellation."""
        assets, transcripts = [], []
        token = _outputs.set((assets, transcripts))
        try:
            yield
        except BaseException:
            with self.db.connect() as db:
                for identifier in transcripts:
                    db.execute("DELETE FROM transcripts WHERE id=?", (identifier,))
                for identifier, _ in assets:
                    db.execute("DELETE FROM assets WHERE id=?", (identifier,))
            for _, path in assets:
                path.unlink(missing_ok=True)
            raise
        finally:
            _outputs.reset(token)

    def projects(self) -> list[dict]:
        return self.db.rows("""SELECT p.*, COUNT(a.id) AS asset_count, COALESCE(SUM(a.duration),0) AS duration
          FROM projects p LEFT JOIN assets a ON a.project_id=p.id AND a.id NOT IN (SELECT asset_id FROM asset_trash) WHERE p.id NOT IN (SELECT project_id FROM project_trash) GROUP BY p.id ORDER BY p.modified DESC""")

    def require_project(self, project_id: str):
        if not self.db.rows(
            "SELECT id FROM projects WHERE id=? AND id NOT IN (SELECT project_id FROM project_trash)",
            (project_id,),
        ):
            raise NotFound("project_not_found")

    def create_project(self, name: str, template: str = "empty") -> dict:
        from .templates import documents

        initial = documents(template)
        name = name.strip()
        if not name or len(name) > 120:
            raise DomainError("invalid_name")
        identifier, stamp = str(uuid.uuid4()), now()
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO projects(id,name,created,modified,application_version) VALUES(?,?,?,?,?)",
                (identifier, name, stamp, stamp, VERSION),
            )
            db.execute(
                "INSERT INTO history(project_id,action,at) VALUES(?,?,?)",
                (identifier, "created", stamp),
            )
            for kind, content in initial.items():
                encoded = json.dumps(content)
                db.execute(
                    "INSERT INTO documents(project_id,kind,content,revision,updated) VALUES(?,?,?,1,?)",
                    (identifier, kind, encoded, stamp),
                )
                db.execute(
                    "INSERT INTO document_revisions(project_id,kind,content,revision,created) VALUES(?,?,?,1,?)",
                    (identifier, kind, encoded, stamp),
                )
        return next(p for p in self.projects() if p["id"] == identifier)

    def update_project(self, project_id: str, name: str, favorite: bool):
        self.require_project(project_id)
        if not name.strip() or len(name) > 120:
            raise DomainError("invalid_name")
        with self.db.connect() as db:
            db.execute(
                "UPDATE projects SET name=?,favorite=?,modified=? WHERE id=?",
                (name.strip(), int(favorite), now(), project_id),
            )
        return next(p for p in self.projects() if p["id"] == project_id)

    def delete_project(self, project_id: str):
        self.require_project(project_id)
        with self.db.connect() as db:
            if db.execute(
                "SELECT 1 FROM jobs WHERE project_id=? AND state IN ('queued','running')",
                (project_id,),
            ).fetchone():
                raise DomainError("active_jobs")
            # Managed asset files are retained for recovery; database references are deleted atomically.
            db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def import_file(
        self,
        project_id: str,
        source: Path,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        from .conversion import decoded_audio

        if request_id is not None:
            try:
                request_id = str(uuid.UUID(request_id))
            except (ValueError, AttributeError) as exc:
                raise DomainError("invalid_request_id") from exc
        self.require_project(project_id)
        with decoded_audio(source, self.db.root) as decoded:
            return self._import_pcm(
                project_id, decoded, display_name or source.name, request_id
            )

    def _import_pcm(
        self,
        project_id: str,
        source: Path,
        display_name: str,
        request_id: str | None = None,
    ) -> dict:
        self.require_project(project_id)
        if source.is_symlink():
            raise MediaError("symlink_not_allowed")
        info = probe(source)
        identifier = str(uuid.uuid4())
        target = self.assets / f"{identifier}.wav"
        temporary = target.with_suffix(".part")
        committed = False
        try:
            with (
                source.open("rb") as input_stream,
                temporary.open("xb") as output_stream,
            ):
                copied = 0
                while block := input_stream.read(1024 * 1024):
                    copied += len(block)
                    if copied > 512 * 1024 * 1024:
                        raise MediaError("media_size_or_path")
                    output_stream.write(block)
            info = probe(temporary)
            digest = checksum(temporary)
            with self.db.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if request_id is not None:
                    receipt = db.execute(
                        "SELECT asset_id,sha256 FROM import_receipts WHERE project_id=? AND request_id=?",
                        (project_id, request_id),
                    ).fetchone()
                    if receipt:
                        if receipt["sha256"] != digest:
                            raise DomainError("import_request_conflict")
                        return self.asset(receipt["asset_id"])
                temporary.replace(target)
                db.execute(
                    """INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        identifier,
                        project_id,
                        display_name[:240],
                        target.name,
                        info["duration"],
                        info["sample_rate"],
                        info["channels"],
                        info["frames"],
                        info["size"],
                        digest,
                        now(),
                    ),
                )
                if request_id is not None:
                    db.execute(
                        "INSERT INTO import_receipts VALUES(?,?,?,?)",
                        (project_id, request_id, identifier, digest),
                    )
                db.execute(
                    "UPDATE projects SET modified=? WHERE id=?", (now(), project_id)
                )
            committed = True
            result = self.asset(identifier)
            if _outputs.get() is not None:
                _outputs.get()[0].append((identifier, target))
            return result
        except Exception:
            if not committed:
                target.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def asset(self, identifier: str) -> dict:
        rows = self.db.rows("SELECT * FROM assets WHERE id=?", (identifier,))
        if not rows:
            raise NotFound("asset_not_found")
        self.require_project(rows[0]["project_id"])
        if self.db.rows("SELECT 1 FROM asset_trash WHERE asset_id=?", (identifier,)):
            raise NotFound("asset_in_trash")
        return rows[0]

    def asset_path(self, identifier: str) -> Path:
        asset = self.asset(identifier)
        path = (self.assets / asset["path"]).resolve()
        if path.parent != self.assets.resolve() or not path.is_file():
            raise NotFound("asset_unavailable")
        return path

    def create_job(
        self, asset_id: str, kind: str = "analyze", options: dict | None = None
    ) -> dict:
        asset = self.asset(asset_id)
        identifier, stamp = str(uuid.uuid4()), now()
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,project_id,asset_id,kind,state,created,updated) VALUES(?,?,?,?,?,?,?)",
                (
                    identifier,
                    asset["project_id"],
                    asset_id,
                    kind,
                    "queued",
                    stamp,
                    stamp,
                ),
            )
            db.execute(
                "UPDATE jobs SET options=? WHERE id=?",
                (json.dumps(options or {}), identifier),
            )
        return self.job(identifier)

    def job(self, identifier: str) -> dict:
        rows = self.db.rows("SELECT * FROM jobs WHERE id=?", (identifier,))
        if not rows:
            raise NotFound("job_not_found")
        row = rows[0]
        row["result"] = json.loads(row["result"]) if row["result"] else None
        return row

    def jobs(self, archived=False) -> list[dict]:
        # A bounded summary: full job options and transcript words never cross polling IPC.
        rows = self.db.rows(
            "SELECT * FROM jobs WHERE (project_id IS NULL OR project_id NOT IN (SELECT project_id FROM project_trash)) "
            "AND EXISTS(SELECT 1 FROM job_archive WHERE job_id=jobs.id)=? "
            "ORDER BY created DESC, id DESC LIMIT 200",
            (int(archived),),
        )
        output, size = [], 2
        for row in rows:
            options = (
                json.loads(row.pop("options", "{}"))
                if row["kind"] == "model_operation"
                else None
            )
            row.pop("options", None)
            if options is not None:
                row["model_id"] = options["model_id"]
                row["operation"] = options["action"]
            result = json.loads(row["result"]) if row["result"] else None
            if isinstance(result, dict):
                result.pop("segments", None)
                result.pop("words", None)
                result.pop("text", None)
            row["result"] = result
            encoded_size = len(json.dumps(row, ensure_ascii=True).encode()) + 1
            if encoded_size > 3 * 1024 * 1024:
                row["result"] = None
                row["result_omitted"] = True
                encoded_size = len(json.dumps(row).encode()) + 1
            if size + encoded_size > 3 * 1024 * 1024:
                break
            size += encoded_size
            output.append(row)
        return output

    def archive_completed_jobs(self):
        """Hide successful jobs without deleting provenance or dependency results."""
        with self.db.connect() as db:
            count = db.execute(
                "INSERT OR IGNORE INTO job_archive(job_id,archived_at) "
                "SELECT id,? FROM jobs WHERE state='completed' "
                "AND (project_id IS NULL OR project_id NOT IN (SELECT project_id FROM project_trash))",
                (now(),),
            ).rowcount
        return {"archived": count}

    def restore_archived_jobs(self):
        with self.db.connect() as db:
            count = db.execute(
                "DELETE FROM job_archive WHERE job_id IN "
                "(SELECT id FROM jobs WHERE (project_id IS NULL OR project_id NOT IN (SELECT project_id FROM project_trash)))"
            ).rowcount
        return {"restored": count}

    def cancel(self, identifier: str):
        self.job(identifier)
        with self.db.connect() as db:
            db.execute(
                """UPDATE jobs SET cancel_requested=1,
             state=CASE WHEN state='queued' THEN 'cancelled' ELSE state END,updated=?
             WHERE id=? AND state IN ('queued','running')""",
                (now(), identifier),
            )

    def retry(self, identifier: str):
        job = self.job(identifier)
        if job["workflow_id"]:
            raise DomainError("retry_workflow_required")
        if job["state"] not in {"failed", "cancelled", "interrupted"}:
            raise DomainError("job_not_retryable")
        if job["kind"] == "model_operation":
            from .model_jobs import create

            return create(self, json.loads(job["options"]))
        return (
            self.create_job(job["asset_id"], job["kind"], json.loads(job["options"]))
            if job["asset_id"]
            else self.create_tts_job(
                job["project_id"], json.loads(job["options"]), job["kind"]
            )
        )

    def create_tts_job(self, project_id: str, options: dict, kind: str = "tts"):
        self.require_project(project_id)
        identifier, stamp = str(uuid.uuid4()), now()
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO jobs(id,project_id,kind,state,created,updated,options) VALUES(?,?,?,'queued',?,?,?)",
                (identifier, project_id, kind, stamp, stamp, json.dumps(options)),
            )
        return self.job(identifier)

    def save_transcript(self, job, result):
        validate_segments(result["segments"], self.asset(job["asset_id"])["duration"])
        identifier = str(uuid.uuid4())
        with self.db.connect() as db:
            db.execute(
                "INSERT INTO transcripts(id,job_id,project_id,asset_id,segments,language,updated) VALUES(?,?,?,?,?,?,?)",
                (
                    identifier,
                    job["id"],
                    job["project_id"],
                    job["asset_id"],
                    json.dumps(result["segments"]),
                    result["language"],
                    now(),
                ),
            )
        if _outputs.get() is not None:
            _outputs.get()[1].append(identifier)
        return identifier

    def import_subtitles(self, asset_id, text, format, language, request_id):
        from .subtitle_import import parse

        try:
            identifier = str(uuid.UUID(request_id))
        except (ValueError, AttributeError) as exc:
            raise DomainError("invalid_request_id") from exc
        asset = self.asset(asset_id)
        segments = parse(text, format, asset["duration"])
        encoded = json.dumps(segments)
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.asset(asset_id)  # Recheck trash while holding the write transaction.
            previous = db.execute(
                "SELECT * FROM transcripts WHERE id=?", (identifier,)
            ).fetchone()
            if previous:
                if (
                    previous["asset_id"] != asset_id
                    or previous["segments"] != encoded
                    or previous["language"] != language
                ):
                    raise DomainError("import_request_conflict")
            else:
                db.execute(
                    "INSERT INTO transcripts(id,job_id,project_id,asset_id,segments,language,updated) VALUES(?,NULL,?,?,?,?,?)",
                    (
                        identifier,
                        asset["project_id"],
                        asset_id,
                        encoded,
                        language,
                        now(),
                    ),
                )
        return next(t for t in self.transcripts(summary=True) if t["id"] == identifier)

    def transcripts(self, summary=False):
        rows = self.db.rows(
            "SELECT * FROM transcripts WHERE project_id NOT IN (SELECT project_id FROM project_trash) AND asset_id NOT IN (SELECT asset_id FROM asset_trash) ORDER BY updated DESC"
        )
        for row in rows:
            row["segments"] = json.loads(row["segments"])
            if summary:
                row["segments"] = [
                    {k: v for k, v in segment.items() if k != "words"}
                    for segment in row["segments"]
                ]
        return rows

    def edit_transcript(self, identifier, revision, segments):
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT t.*, a.duration FROM transcripts t JOIN assets a ON a.id=t.asset_id WHERE t.id=? "
                "AND t.project_id NOT IN (SELECT project_id FROM project_trash) "
                "AND t.asset_id NOT IN (SELECT asset_id FROM asset_trash)",
                (identifier,),
            ).fetchone()
            if current is None:
                raise NotFound("transcript_not_found")
            if current["revision"] != revision:
                raise DomainError("transcript_revision_conflict")
            segments = merge_transcript_edit(
                json.loads(current["segments"]), segments, current["duration"]
            )
            result = db.execute(
                "UPDATE transcripts SET segments=?,revision=revision+1,updated=? WHERE id=? AND revision=?",
                (json.dumps(segments), now(), identifier, revision),
            )
            if not result.rowcount:
                raise DomainError("transcript_revision_conflict")
        return next(t for t in self.transcripts() if t["id"] == identifier)

    def transcript_revisions(self, identifier, before=None):
        if before is not None and (type(before) is not int or before < 1):
            raise DomainError("invalid_page")
        with self.db.connect() as db:
            db.execute("BEGIN")
            active = db.execute(
                "SELECT id FROM transcripts WHERE id=? "
                "AND project_id NOT IN (SELECT project_id FROM project_trash) "
                "AND asset_id NOT IN (SELECT asset_id FROM asset_trash)",
                (identifier,),
            ).fetchone()
            if active is None:
                raise NotFound("transcript_not_found")
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT revision,created,length(CAST(segments AS BLOB)) AS bytes "
                    "FROM transcript_revisions WHERE transcript_id=? AND (? IS NULL OR revision<?) "
                    "ORDER BY revision DESC LIMIT 51",
                    (identifier, before, before),
                )
            ]
        return {
            "items": rows[:50],
            "next_cursor": rows[49]["revision"] if len(rows) > 50 else None,
        }

    def restore_transcript(self, identifier, source_revision, expected_revision):
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute(
                "SELECT t.*,a.duration FROM transcripts t JOIN assets a ON a.id=t.asset_id WHERE t.id=? "
                "AND t.project_id NOT IN (SELECT project_id FROM project_trash) "
                "AND t.asset_id NOT IN (SELECT asset_id FROM asset_trash)",
                (identifier,),
            ).fetchone()
            if current is None:
                raise NotFound("transcript_not_found")
            if current["revision"] != expected_revision:
                raise DomainError("transcript_revision_conflict")
            snapshot = db.execute(
                "SELECT segments,language FROM transcript_revisions WHERE transcript_id=? AND revision=?",
                (identifier, source_revision),
            ).fetchone()
            if snapshot is None:
                raise NotFound("document_revision_not_found")
            segments = json.loads(snapshot["segments"])
            validate_segments(segments, current["duration"])
            stamp = now()
            db.execute(
                "UPDATE transcripts SET segments=?,language=?,revision=revision+1,updated=? WHERE id=?",
                (snapshot["segments"], snapshot["language"], stamp, identifier),
            )
            result = {
                **dict(current),
                "segments": segments,
                "language": snapshot["language"],
                "revision": expected_revision + 1,
                "updated": stamp,
            }
            result.pop("duration", None)
        return result

    def document(self, project_id, kind):
        self.require_project(project_id)
        rows = self.db.rows(
            "SELECT * FROM documents WHERE project_id=? AND kind=?", (project_id, kind)
        )
        if not rows:
            return {
                "project_id": project_id,
                "kind": kind,
                "revision": 0,
                "content": {},
            }
        row = rows[0]
        row["content"] = json.loads(row["content"])
        return row

    def save_document(self, project_id, kind, content, revision):
        self.require_project(project_id)
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.require_project(project_id)
            content = validate_document(self, project_id, kind, content)
            if revision == 0:
                try:
                    db.execute(
                        "INSERT INTO documents(project_id,kind,content,updated) VALUES(?,?,?,?)",
                        (project_id, kind, json.dumps(content), now()),
                    )
                except sqlite3.IntegrityError as exc:
                    raise DomainError("document_revision_conflict") from exc
            else:
                cursor = db.execute(
                    "UPDATE documents SET content=?,revision=revision+1,updated=? WHERE project_id=? AND kind=? AND revision=?",
                    (json.dumps(content), now(), project_id, kind, revision),
                )
                if not cursor.rowcount:
                    raise DomainError("document_revision_conflict")
            # Snapshot and current document commit together; conflicts create neither.
            db.execute(
                "INSERT INTO document_revisions(project_id,kind,revision,content,created) "
                "SELECT project_id,kind,revision,content,updated FROM documents WHERE project_id=? AND kind=?",
                (project_id, kind),
            )
            db.execute("UPDATE projects SET modified=? WHERE id=?", (now(), project_id))
            saved = dict(
                db.execute(
                    "SELECT * FROM documents WHERE project_id=? AND kind=?",
                    (project_id, kind),
                ).fetchone()
            )
            saved["content"] = json.loads(saved["content"])
        return saved

    def document_revisions(self, project_id, kind, before=None):
        self.document(project_id, kind)
        rows = self.db.rows(
            "SELECT revision,created,length(CAST(content AS BLOB)) AS bytes FROM document_revisions "
            "WHERE project_id=? AND kind=? AND (? IS NULL OR revision<?) ORDER BY revision DESC LIMIT 51",
            (project_id, kind, before, before),
        )
        return {
            "items": rows[:50],
            "next_cursor": rows[49]["revision"] if len(rows) > 50 else None,
        }

    def restore_document(self, project_id, kind, source_revision, expected_revision):
        self.require_project(project_id)
        rows = self.db.rows(
            "SELECT content FROM document_revisions WHERE project_id=? AND kind=? AND revision=?",
            (project_id, kind, source_revision),
        )
        if not rows:
            raise NotFound("document_revision_not_found")
        # Restoring creates a new revision; it never overwrites previous history.
        return self.save_document(
            project_id, kind, json.loads(rows[0]["content"]), expected_revision
        )

    def active_assets(self, project_id=None):
        if project_id:
            self.require_project(project_id)
        return self.db.rows(
            "SELECT * FROM assets WHERE id NOT IN (SELECT asset_id FROM asset_trash) "
            "AND project_id NOT IN (SELECT project_id FROM project_trash) "
            "AND (? IS NULL OR project_id=?) ORDER BY created DESC",
            (project_id, project_id),
        )

    def trash_project(self, identifier):
        self.require_project(identifier)
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM jobs WHERE project_id=? AND state IN ('queued','running')",
                (identifier,),
            ).fetchone():
                raise DomainError("active_jobs")
            db.execute(
                "INSERT OR IGNORE INTO project_trash VALUES(?,?)", (identifier, now())
            )

    def trash_asset(self, identifier):
        asset = self.asset(identifier)
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Pending jobs may reference an asset through timeline/workflow options.
            if db.execute(
                "SELECT 1 FROM jobs WHERE project_id=? AND state IN ('queued','running')",
                (asset["project_id"],),
            ).fetchone():
                raise DomainError("active_jobs")
            if db.execute(
                "SELECT 1 FROM documents WHERE project_id=? AND instr(content,?)>0",
                (asset["project_id"], identifier),
            ).fetchone():
                raise DomainError("asset_used_in_document")
            db.execute(
                "INSERT OR IGNORE INTO asset_trash VALUES(?,?)", (identifier, now())
            )

    def trash_items(self, offset=0):
        if not isinstance(offset, int) or offset < 0 or offset > 1_000_000:
            raise DomainError("invalid_page")
        rows = self.db.rows(
            """SELECT p.id,p.name,'project' AS kind,t.deleted_at,
            (SELECT COALESCE(SUM(size),0) FROM assets WHERE project_id=p.id) AS bytes
            FROM projects p JOIN project_trash t ON p.id=t.project_id
            UNION ALL SELECT a.id,a.name,'asset' AS kind,t.deleted_at,a.size AS bytes
            FROM assets a JOIN asset_trash t ON a.id=t.asset_id
            WHERE a.project_id NOT IN (SELECT project_id FROM project_trash)
            ORDER BY deleted_at DESC,id DESC LIMIT 51 OFFSET ?""",
            (offset,),
        )
        return {
            "items": rows[:50],
            "next_offset": offset + 50 if len(rows) > 50 else None,
        }

    def restore_trash(self, kind, identifier):
        if kind not in {"project", "asset"}:
            raise DomainError("invalid_trash_kind")
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if kind == "asset":
                row = db.execute(
                    "SELECT project_id FROM assets WHERE id=?", (identifier,)
                ).fetchone()
                if row is None:
                    raise NotFound("asset_not_found")
                if db.execute(
                    "SELECT 1 FROM project_trash WHERE project_id=?",
                    (row["project_id"],),
                ).fetchone():
                    raise DomainError("restore_project_first")
                cursor = db.execute(
                    "DELETE FROM asset_trash WHERE asset_id=?", (identifier,)
                )
            else:
                cursor = db.execute(
                    "DELETE FROM project_trash WHERE project_id=?", (identifier,)
                )
            if not cursor.rowcount:
                raise NotFound("trash_item_not_found")
        return {"restored": identifier}
