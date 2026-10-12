"""Shared AI queue submission and bounded offline worker execution."""

from .errors import DomainError
from .jobs import JobRunner
from .workflows import ASROptions, TTSOptions, WorkflowService


def submit_tts(core, models, project_id, text, options):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 5000:
        raise DomainError("invalid_speech_text")
    settings = TTSOptions.model_validate(options).model_dump()
    WorkflowService(core, models).validate_requirements(
        {"steps": [{"kind": "tts", "options": settings}]}
    )
    return core.create_tts_job(
        project_id, {**settings, "text": text, "project_id": project_id}
    )


def submit_transcription(core, models, asset_id, options):
    settings = ASROptions.model_validate(options).model_dump()
    WorkflowService(core, models).validate_requirements(
        {"steps": [{"kind": "transcribe", "options": settings}]}
    )
    return core.create_job(asset_id, "transcribe", {**settings, "asset_id": asset_id})


def drain(core, models, limit=256, workflow_id=None, job_id=None):
    """Drain ready jobs under the CLI's workspace lock, without starting a daemon."""
    if not 1 <= limit <= 256:
        raise DomainError("invalid_worker_limit")
    runner = JobRunner(core, models)
    processed = []
    identifier = None
    try:
        for _ in range(limit):
            identifier = runner.claim_next(workflow_id=workflow_id, job_id=job_id)
            if identifier is None:
                break
            runner.execute(identifier)
            job = core.job(identifier)
            processed.append(
                {
                    "id": identifier,
                    "kind": job["kind"],
                    "state": job["state"],
                    "error": job["error"],
                }
            )
    except KeyboardInterrupt:
        if identifier:
            from .core import now

            with core.db.connect() as db:
                db.execute(
                    "UPDATE jobs SET state='interrupted',updated=? WHERE id=? AND state='running'",
                    (now(), identifier),
                )
        raise
    return {
        "processed": processed,
        "failed": sum(j["state"] == "failed" for j in processed),
    }
