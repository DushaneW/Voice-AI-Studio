"""Authenticated loopback API; all blocking core operations run outside the event loop."""

from __future__ import annotations

import hmac
import json
import os
import platform
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from . import VERSION
from .core import Core
from .engines import hardware, registry
from .errors import DomainError, NotFound
from .jobs import JobRunner
from .media import MediaError
from .models import ModelManager
from .workflows import WorkflowService


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    favorite: bool = False


class CreateProjectInput(ProjectInput):
    template: Literal["empty", "podcast", "multitrack", "audiobook"] = "empty"


class DuplicateProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=120)


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    path: str = Field(max_length=4096)
    request_id: str | None = Field(default=None, max_length=36)


class NotificationSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: int | None = Field(default=None, gt=0, le=9223372036854775807)
    unread_only: bool = False


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=100)


class CacheClearInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]


class TrashSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(default=0, ge=0, le=1_000_000)


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str


class SettingsInput(BaseModel):
    recording_sample_rate: Literal[24000, 44100, 48000] = 48000
    recording_channels: Literal[1, 2] = 1
    recording_gain: float = Field(default=1, ge=0, le=4, allow_inf_nan=False)
    recording_preroll: Literal[0, 1, 2, 3, 5] = 0
    recording_countdown: Literal[0, 3, 5] = 0
    playback_volume: float = Field(default=1, ge=0, le=1, allow_inf_nan=False)
    playback_muted: bool = False
    transcription_model: str | None = Field(
        default=None, min_length=1, max_length=100, pattern="^[a-zA-Z0-9_-]+$"
    )
    transcription_language: str | None = Field(default=None, pattern="^[a-z]{2,3}$")
    transcription_device: Literal["cpu", "cuda"] = "cpu"
    tts_voice: str | None = Field(
        default=None, pattern="^[a-z][a-z]_[a-z0-9_]+$", max_length=100
    )
    tts_speed: float = Field(default=1, ge=0.5, le=2, allow_inf_nan=False)
    model_downloads_allowed: bool = True
    waveform_cache_enabled: bool = True
    waveform_cache_mb: Literal[0, 128, 512, 1024] = 0
    last_project_id: str | None = Field(default=None, min_length=36, max_length=36)
    recent_project_ids: list[Annotated[str, Field(min_length=36, max_length=36)]] = (
        Field(default_factory=list, max_length=20)
    )
    autosave_seconds: Literal[0, 5, 15, 30, 60] = 0
    theme: Literal["dark", "light", "system"] = "dark"
    motion: Literal["system", "full", "reduced"] = "system"
    sidebar_collapsed: bool = False
    model_config = ConfigDict(extra="forbid")
    language: str = Field(pattern="^(en|pl)$")
    inspector: bool = True
    workspace: str = Field(
        pattern="^(home|projects|media|jobs|settings|diagnostics|models|tts|transcription|voices|timeline|audiobook|dubbing|workflows)$"
    )


class TranscribeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    model_id: str = "whisper-tiny"
    language: str | None = Field(default=None, pattern="^[a-z]{2,3}$")
    device: str = Field(default="cpu", pattern="^(cpu|cuda)$")


class TTSInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    model_id: str = "kokoro-v1"
    text: str = Field(min_length=1, max_length=5000)
    voice: str = Field(pattern="^[a-z][a-z]_[a-z0-9_]+$")
    language: str = Field(
        default="en-us", pattern="^(en-us|en-gb|fr-fr|ja|zh|es|hi|it|pt-br)$"
    )
    speed: float = Field(default=1, ge=0.5, le=2)


class SegmentEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    text: str = Field(max_length=10000)
    speaker: str | None = Field(default=None, min_length=1, max_length=80)


class SubtitleImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(max_length=36)
    request_id: str = Field(max_length=36)
    text: str = Field(min_length=1, max_length=512 * 1024)
    format: Literal["srt", "vtt"]
    language: str = Field(default="und", pattern=r"^[a-z]{2,3}$")


class TranscriptEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    segments: list[SegmentEdit] = Field(max_length=10000)


class ChapterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=5000)


class AudiobookInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    model_id: str = "kokoro-v1"
    voice: str = Field(pattern="^[a-z][a-z]_[a-z0-9_]+$")
    language: str = Field(
        default="en-us", pattern="^(en-us|en-gb|fr-fr|ja|zh|es|hi|it|pt-br)$"
    )
    speed: float = Field(default=1, ge=0.5, le=2)
    gap: float = Field(default=1, ge=0, le=10)
    chapters: list[ChapterInput] = Field(min_length=1, max_length=50)


class DubbingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    transcript_id: str
    model_id: str = "kokoro-v1"
    voice: str = Field(pattern="^[a-z][a-z]_[a-z0-9_]+$")
    language: str = Field(
        default="en-us", pattern="^(en-us|en-gb|fr-fr|ja|zh|es|hi|it|pt-br)$"
    )
    speed: float = Field(default=1, ge=0.5, le=2)


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=4096)


class ClipInput(BaseModel):
    track_id: str = Field(default="main", min_length=1, max_length=80)
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    offset: float = Field(default=0, ge=0, le=3600, allow_inf_nan=False)
    trim_start: float = Field(default=0, ge=0, allow_inf_nan=False)
    trim_end: float = Field(gt=0, allow_inf_nan=False)
    gain: float = Field(default=1, ge=0, le=4, allow_inf_nan=False)
    fade_in: float = Field(default=0, ge=0, le=60, allow_inf_nan=False)
    fade_out: float = Field(default=0, ge=0, le=60, allow_inf_nan=False)


class TimelineInput(BaseModel):
    tracks: list[dict] | None = Field(default=None, min_length=1, max_length=32)
    sample_rate: Literal[24000, 44100, 48000] = 24000
    channels: Literal[1, 2] = 1
    model_config = ConfigDict(extra="forbid")
    project_id: str
    clips: list[ClipInput] = Field(min_length=1, max_length=64)


class DocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    content: dict


class DocumentRestoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_revision: int = Field(ge=1)
    expected_revision: int = Field(ge=0)


class RevisionSearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    before: int | None = Field(default=None, ge=1)


class WorkflowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    template_id: str
    inputs: list[str] = Field(min_length=1, max_length=64)
    request_key: str = Field(min_length=8, max_length=100)


class WorkflowSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str
    before: str | None = None


class WorkflowRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: str = Field(min_length=8, max_length=100)


class WorkflowTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    definition: dict


def create_app(root: Path, token: str) -> FastAPI:
    if len(token) < 32:
        raise DomainError("token_too_short")
    from .auditlog import configure

    core = Core(root)
    configure(core.db.root)
    models = ModelManager(core.db)
    runner = JobRunner(core, models)
    workflows = WorkflowService(core, models)

    @asynccontextmanager
    async def lifespan(_app):
        runner.start()
        yield
        runner.close()
        models.close()

    def authorize(request: Request):
        # No CORS or browser origins: normal application accesses through Rust IPC.
        if request.headers.get("origin"):
            raise HTTPException(403, detail="origin_forbidden")
        if not hmac.compare_digest(
            request.headers.get("authorization", ""), f"Bearer {token}"
        ):
            raise HTTPException(401, detail="unauthorized")

    app = FastAPI(
        title="NEXUS runtime",
        version=VERSION,
        lifespan=lifespan,
        dependencies=[Depends(authorize)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.core = core

    @app.exception_handler(NotFound)
    async def not_found(_request, exc):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(MediaError)
    async def invalid_media(_request, exc):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(DomainError)
    async def domain_error(_request, exc):
        return JSONResponse(status_code=409, content={"detail": exc.code})

    @app.exception_handler(OSError)
    async def storage_error(_request, _exc):
        return JSONResponse(status_code=503, content={"detail": "storage_unavailable"})

    @app.exception_handler(Exception)
    async def unexpected(_request, exc):
        # A non-domain exception is a defect, not a client conflict. Log only the
        # exception class: messages may contain paths or user text.
        from .auditlog import request_failed

        request_failed(type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "internal_error"})

    @app.post("/shutdown")
    def shutdown():
        callback = getattr(app.state, "shutdown", None)
        if callback:
            callback()
        return {"accepted": callback is not None}

    @app.get("/health")
    def health():
        return {"status": "ready", "api_version": "1", "application_version": VERSION}

    @app.get("/v1/projects")
    def projects():
        return core.projects()

    @app.post("/v1/projects", status_code=201)
    def create_project(data: CreateProjectInput):
        return core.create_project(data.name, data.template)

    @app.post("/v1/projects/{identifier}/duplicate", status_code=201)
    def duplicate_project(identifier: str, data: DuplicateProjectInput):
        from .project_copy import queue

        return queue(core, identifier, data.request_id, data.name)

    @app.post("/v1/projects/{identifier}/repair-plan", status_code=201)
    def plan_project_repair(identifier: str):
        return core.create_tts_job(identifier, {}, "plan_repair")

    @app.post("/v1/jobs/{identifier}/apply-repair", status_code=201)
    def apply_project_repair(identifier: str, data: CacheClearInput):
        from .project_repair import queue_apply

        return queue_apply(core, identifier)

    @app.post("/v1/projects/{identifier}/validate", status_code=201)
    def validate_project(identifier: str):
        return core.create_tts_job(identifier, {}, "validate_project")

    @app.patch("/v1/projects/{identifier}")
    def update_project(identifier: str, data: ProjectInput):
        return core.update_project(identifier, data.name, data.favorite)

    @app.delete("/v1/projects/{identifier}", status_code=204)
    def delete_project(identifier: str):
        core.trash_project(identifier)

    @app.post("/v1/notifications/search")
    def notifications(data: NotificationSearchInput):
        from .notifications import search

        return search(core, data.before, data.unread_only)

    @app.post("/v1/notifications/{identifier}/read")
    def read_notification(identifier: int):
        from .notifications import mark_read

        return mark_read(core, identifier)

    @app.post("/v1/jobs/{identifier}/events")
    def job_events(identifier: str, data: NotificationSearchInput):
        from .notifications import events

        return events(core, identifier, data.before)

    @app.post("/v1/search")
    def search_workspace(data: SearchInput):
        from .search import search

        return search(core, data.query)

    @app.get("/v1/storage")
    def storage_inventory():
        from .storage import inventory

        return inventory(core)

    @app.post("/v1/storage/waveforms/clear")
    def clear_waveform_cache(data: CacheClearInput):
        from .storage import clear_waveforms

        return clear_waveforms(core.db.root)

    @app.get("/v1/assets")
    def assets(project_id: str | None = None):
        return core.active_assets(project_id)

    @app.delete("/v1/assets/{identifier}", status_code=204)
    def trash_asset(identifier: str):
        core.trash_asset(identifier)

    @app.post("/v1/trash/search")
    def search_trash(data: TrashSearchInput):
        return core.trash_items(data.offset)

    @app.post("/v1/trash/{kind}/{identifier}/restore")
    def restore_trash(kind: str, identifier: str):
        return core.restore_trash(kind, identifier)

    @app.post("/v1/assets/import", status_code=201)
    def import_asset(data: ImportInput):
        return core.import_file(
            data.project_id, Path(data.path), request_id=data.request_id
        )

    @app.get("/v1/assets/{identifier}/waveform")
    def waveform(identifier: str):
        from .waveforms import read

        asset = core.asset(identifier)
        return {
            "analysis": read(core.db.root, asset["sha256"])
            if core.db.settings().get("waveform_cache_enabled", True)
            else None
        }

    @app.get("/v1/assets/{identifier}/audio")
    def audio(identifier: str):
        return FileResponse(
            core.asset_path(identifier), media_type="audio/wav", filename="audio.wav"
        )

    @app.post("/v1/jobs", status_code=201)
    def create_job(data: JobInput):
        return core.create_job(data.asset_id)

    @app.get("/v1/jobs")
    def jobs():
        return core.jobs()

    @app.get("/v1/jobs/archive")
    def archived_jobs():
        return core.jobs(archived=True)

    @app.post("/v1/jobs/archive")
    def archive_jobs():
        return core.archive_completed_jobs()

    @app.post("/v1/jobs/archive/restore")
    def restore_jobs():
        return core.restore_archived_jobs()

    @app.get("/v1/jobs/{identifier}/status")
    def job_status(identifier: str):
        row = core.job(identifier)
        if row["project_id"] is not None:
            core.require_project(row["project_id"])
        result = row["result"] if isinstance(row["result"], dict) else {}
        return {
            "id": row["id"],
            "state": row["state"],
            "error": row["error"],
            "asset_id": result.get("asset_id"),
        }

    @app.post("/v1/jobs/{identifier}/cancel")
    def cancel(identifier: str):
        core.cancel(identifier)
        return core.job(identifier)

    @app.post("/v1/jobs/{identifier}/retry", status_code=201)
    def retry(identifier: str):
        return core.retry(identifier)

    @app.get("/v1/settings")
    def settings():
        return {
            "recording_sample_rate": 48000,
            "recording_channels": 1,
            "recording_gain": 1,
            "recording_preroll": 0,
            "recording_countdown": 0,
            "playback_volume": 1,
            "playback_muted": False,
            "transcription_model": None,
            "transcription_language": None,
            "transcription_device": "cpu",
            "tts_voice": None,
            "tts_speed": 1,
            "model_downloads_allowed": True,
            "last_project_id": None,
            "recent_project_ids": [],
            "waveform_cache_enabled": True,
            "waveform_cache_mb": 0,
            "autosave_seconds": 0,
            "language": "en",
            "theme": "dark",
            "motion": "system",
            "sidebar_collapsed": False,
            "inspector": True,
            "workspace": "home",
            **core.db.settings(),
        }

    @app.put("/v1/settings")
    def save_settings(data: SettingsInput):
        if data.transcription_model is not None:
            spec = models.require(data.transcription_model)
            if spec["engine"] != "faster-whisper":
                raise DomainError("invalid_engine")
            if data.transcription_device not in spec.get("devices", ["cpu"]):
                raise DomainError("unsupported_device")
        with core.db.connect() as db:
            for key, value in data.model_dump().items():
                db.execute(
                    "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)),
                )
        return data

    @app.get("/v1/security")
    def security_report():
        from .security import report

        return report(core, models)

    @app.get("/v1/privacy")
    def privacy_report():
        from .security import privacy

        return privacy(core, models)

    @app.get("/v1/diagnostics")
    def diagnostics():
        from .system_info import gpu_inventory, host_info

        usage = shutil.disk_usage(core.db.root)
        return {
            "application_version": VERSION,
            "api_version": "1",
            "python": platform.python_version(),
            "os": platform.system(),
            "cpu_logical": os.cpu_count(),
            "host": host_info(),
            "gpu_inventory": gpu_inventory(),
            "engines": registry(),
            "storage_free": usage.free,
            "storage_total": usage.total,
            "ffmpeg_available": shutil.which("ffmpeg") is not None,
            "gpu": hardware(),
            "runtime": "healthy",
            "database_schema": core.db.rows("PRAGMA user_version")[0]["user_version"],
            "packaged": bool(getattr(sys, "frozen", False)),
        }

    @app.get("/v1/engines")
    def engines():
        return registry()

    @app.get("/v1/models")
    def model_list():
        return models.list()

    @app.post("/v1/models/{identifier}/{action}")
    def model_action(identifier: str, action: str):
        from .model_jobs import ACTIONS, cancel, queue

        if action in ACTIONS:
            job = queue(core, models, identifier, action)
            return {"accepted": True, "job_id": job["id"]}
        if action in {"pause", "cancel"}:
            return cancel(core, models, identifier, pause=action == "pause")
        models.action(identifier, action)
        return {"accepted": True}

    @app.get("/v1/voices")
    def voice_list():
        from .engines.kokoro import voices

        try:
            return voices(models.directory("kokoro-v1"))
        except ValueError:
            return []

    @app.post("/v1/transcribe", status_code=201)
    def transcribe_job(data: TranscribeInput):
        models.directory(data.model_id)
        spec = models.require(data.model_id)
        if spec["engine"] != "faster-whisper":
            raise DomainError("invalid_engine")
        if data.device not in spec.get("devices", ["cpu"]):
            raise DomainError("unsupported_device")
        return core.create_job(data.asset_id, "transcribe", data.model_dump())

    @app.post("/v1/tts", status_code=201)
    def tts_job(data: TTSInput):
        models.directory(data.model_id)
        if models.require(data.model_id)["engine"] != "kokoro-onnx":
            raise DomainError("invalid_engine")
        return core.create_tts_job(data.project_id, data.model_dump())

    @app.get("/v1/transcripts")
    def transcripts():
        return core.transcripts(summary=True)

    @app.post("/v1/transcripts/import", status_code=201)
    def import_subtitles(data: SubtitleImport):
        return core.import_subtitles(
            data.asset_id, data.text, data.format, data.language, data.request_id
        )

    @app.put("/v1/transcripts/{identifier}")
    def edit_transcript(identifier: str, data: TranscriptEdit):
        return core.edit_transcript(
            identifier,
            data.revision,
            [s.model_dump(exclude_unset=True) for s in data.segments],
        )

    @app.get("/v1/transcripts/{identifier}/export/{format}")
    def export_transcript(identifier: str, format: str):
        from .exports import subtitles

        items = [t for t in core.transcripts() if t["id"] == identifier]
        if not items:
            raise NotFound("transcript_not_found")
        return {"text": subtitles(items[0]["segments"], format)}

    @app.post("/v1/transcripts/{identifier}/history")
    def transcript_history(identifier: str, data: RevisionSearchInput):
        return core.transcript_revisions(identifier, data.before)

    @app.post("/v1/transcripts/{identifier}/restore")
    def transcript_restore(identifier: str, data: DocumentRestoreInput):
        result = core.restore_transcript(
            identifier, data.source_revision, data.expected_revision
        )
        return {
            "revision": result["revision"],
            "content": {
                "language": result["language"],
                "segments": [
                    {k: v for k, v in segment.items() if k != "words"}
                    for segment in result["segments"]
                ],
            },
        }

    @app.get("/v1/projects/{identifier}/documents/{kind}")
    def document(identifier: str, kind: str):
        if kind not in {"timeline", "audiobook", "dubbing", "project"}:
            raise DomainError("invalid_document_kind")
        return core.document(identifier, kind)

    @app.put("/v1/projects/{identifier}/documents/{kind}")
    def save_document(identifier: str, kind: str, data: DocumentInput):
        if kind not in {"timeline", "audiobook", "dubbing", "project"}:
            raise DomainError("invalid_document_kind")
        if len(json.dumps(data.content)) > 1024 * 1024:
            raise DomainError("document_too_large")
        return core.save_document(identifier, kind, data.content, data.revision)

    @app.post("/v1/projects/{identifier}/documents/{kind}/history")
    def document_history(identifier: str, kind: str, data: RevisionSearchInput):
        if kind not in {"timeline", "audiobook", "dubbing", "project"}:
            raise DomainError("invalid_document_kind")
        return core.document_revisions(identifier, kind, data.before)

    @app.post("/v1/projects/{identifier}/documents/{kind}/restore")
    def document_restore(identifier: str, kind: str, data: DocumentRestoreInput):
        if kind not in {"timeline", "audiobook", "dubbing", "project"}:
            raise DomainError("invalid_document_kind")
        return core.restore_document(
            identifier, kind, data.source_revision, data.expected_revision
        )

    @app.post("/v1/timeline/render", status_code=201)
    def timeline_render(data: TimelineInput):
        from .timeline import validate, validate_tracks

        options = data.model_dump()
        validate(options["clips"], core, data.project_id)
        validate_tracks(options["tracks"], options["clips"])
        return core.create_tts_job(data.project_id, options, "timeline")

    @app.post("/v1/audiobook", status_code=201)
    def audiobook_job(data: AudiobookInput):
        models.directory(data.model_id)
        if models.require(data.model_id)["engine"] != "kokoro-onnx":
            raise DomainError("invalid_engine")
        return core.create_tts_job(data.project_id, data.model_dump(), "audiobook")

    @app.post("/v1/dubbing", status_code=201)
    def dubbing_job(data: DubbingInput):
        models.directory(data.model_id)
        if models.require(data.model_id)["engine"] != "kokoro-onnx":
            raise DomainError("invalid_engine")
        transcripts = [
            t
            for t in core.transcripts()
            if t["id"] == data.transcript_id and t["project_id"] == data.project_id
        ]
        if not transcripts:
            raise NotFound("transcript_not_found")
        return core.create_tts_job(data.project_id, data.model_dump(), "dubbing")

    @app.post("/v1/projects/{identifier}/backup", status_code=201)
    def backup_project(identifier: str):
        from .backups import create

        return create(core, identifier)

    @app.get("/v1/backups/{identifier}/file")
    def backup_file(identifier: str):
        import uuid

        try:
            uuid.UUID(identifier)
        except ValueError as exc:
            raise NotFound("backup_not_found") from exc
        path = core.db.root / "backups" / (identifier + ".nexus")
        if not path.is_file():
            raise NotFound("backup_not_found")
        return FileResponse(
            path,
            filename="project.nexus",
            background=BackgroundTask(path.unlink, missing_ok=True),
        )

    @app.post("/v1/backups/restore", status_code=201)
    def restore_project(data: RestoreInput):
        from .backups import restore

        return restore(core, Path(data.path))

    @app.get("/v1/workflow-templates")
    def workflow_templates():
        return workflows.templates()

    @app.post("/v1/workflow-templates", status_code=201)
    def workflow_template_create(data: WorkflowTemplateInput):
        return workflows.create_template(data.name, data.description, data.definition)

    @app.delete("/v1/workflow-templates/{identifier}", status_code=204)
    def workflow_template_delete(identifier: str):
        workflows.delete_template(identifier)

    @app.post("/v1/workflows", status_code=201)
    def workflow_start(data: WorkflowInput):
        return workflows.start(
            data.project_id, data.template_id, data.inputs, data.request_key
        )

    @app.post("/v1/workflows/search")
    def workflow_search(data: WorkflowSearch):
        return workflows.list_runs(data.project_id, data.before)

    @app.get("/v1/workflows/{identifier}")
    def workflow_detail(identifier: str):
        return workflows.run(identifier)

    @app.post("/v1/workflows/{identifier}/cancel")
    def workflow_cancel(identifier: str):
        return workflows.cancel(identifier)

    @app.post("/v1/workflows/{identifier}/retry", status_code=201)
    def workflow_retry(identifier: str, data: WorkflowRetry):
        return workflows.retry(identifier, data.request_key)

    return app
