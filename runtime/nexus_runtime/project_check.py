"""Read-only, cancellable project integrity checks executed by the durable worker."""

import hashlib
import json
import wave

from .core import now
from .errors import DomainError
from .media import MAX_BYTES
from .validation import validate_document, validate_segments


def execute(core, project_id, progress, cancelled):
    core.require_project(project_id)
    started = now()
    with core.db.connect() as db:
        db.execute("BEGIN")
        assets = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM assets WHERE project_id=?", (project_id,)
            )
        ]
        documents = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM documents WHERE project_id=?", (project_id,)
            )
        ]
        transcripts = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM transcripts WHERE project_id=?", (project_id,)
            )
        ]
    issues = []
    issue_count = 0
    total = max(1, len(assets) + len(documents) + len(transcripts))
    completed = 0

    def check_cancel():
        if cancelled():
            raise InterruptedError

    def issue(kind, identifier, code):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < 200:
            issues.append({"kind": kind, "id": identifier, "code": code})

    for asset in assets:
        check_cancel()
        try:
            path = core.assets / asset["path"]
            if path.is_symlink() or path.resolve().parent != core.assets.resolve():
                raise DomainError("unsafe_asset_path")
            before = path.stat()
            if before.st_size > MAX_BYTES:
                raise DomainError("media_size_or_path")
            digest = hashlib.sha256()
            read = 0
            with path.open("rb") as stream:
                while block := stream.read(1048576):
                    check_cancel()
                    read += len(block)
                    if read > MAX_BYTES:
                        raise DomainError("media_size_or_path")
                    digest.update(block)
                    progress(
                        (completed + min(0.99, read / max(1, before.st_size))) / total
                    )
            after = path.stat()
            if (before.st_mtime_ns, before.st_size) != (
                after.st_mtime_ns,
                after.st_size,
            ):
                raise DomainError("asset_changed_during_check")
            if read != asset["size"] or digest.hexdigest() != asset["sha256"]:
                issue("asset", asset["id"], "asset_checksum_mismatch")
            with wave.open(str(path), "rb") as stream:
                actual = (
                    stream.getnframes(),
                    stream.getframerate(),
                    stream.getnchannels(),
                )
                expected = (asset["frames"], asset["sample_rate"], asset["channels"])
                if (
                    actual != expected
                    or stream.getsampwidth() != 2
                    or stream.getcomptype() != "NONE"
                ):
                    issue("asset", asset["id"], "asset_metadata_mismatch")
                remaining = stream.getnframes()
                while remaining:
                    check_cancel()
                    data = stream.readframes(min(remaining, 65536))
                    frame_bytes = stream.getnchannels() * stream.getsampwidth()
                    if not data or len(data) % frame_bytes:
                        raise DomainError("truncated_wav")
                    remaining -= len(data) // frame_bytes
        except FileNotFoundError:
            issue("asset", asset["id"], "asset_missing")
        except (OSError, ValueError, wave.Error, EOFError):
            issue("asset", asset["id"], "asset_invalid")
        completed += 1
        progress(completed / total)
    durations = {a["id"]: a["duration"] for a in assets}
    for document in documents:
        check_cancel()
        try:
            validate_document(
                core, project_id, document["kind"], json.loads(document["content"])
            )
        except (ValueError, TypeError, KeyError):
            issue("document", document["kind"], "document_invalid")
        completed += 1
        progress(completed / total)
    for transcript in transcripts:
        check_cancel()
        try:
            validate_segments(
                json.loads(transcript["segments"]), durations[transcript["asset_id"]]
            )
        except (ValueError, TypeError, KeyError):
            issue("transcript", transcript["id"], "transcript_invalid")
        completed += 1
        progress(completed / total)
    check_cancel()
    return {
        "checked_assets": len(assets),
        "checked_documents": len(documents),
        "checked_transcripts": len(transcripts),
        "issues": issues,
        "issue_count": issue_count,
        "omitted_issues": issue_count - len(issues),
        "started": started,
        "finished": now(),
    }
