"""Offline automation using the same workspace rules as the desktop runtime."""

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path

from . import VERSION
from .backups import create, restore
from .core import Core, NotFound
from .errors import DomainError
from .locking import workspace_lock
from .media import MediaError, analyze


def parser():
    root = argparse.ArgumentParser(prog="nexus", description=__doc__)
    root.add_argument("--version", action="version", version=VERSION)
    root.add_argument(
        "--data-dir",
        required=True,
        type=Path,
        help="Workspace directory; desktop must be closed",
    )
    commands = root.add_subparsers(dest="command", required=True)
    projects = commands.add_parser("projects").add_subparsers(
        dest="action", required=True
    )
    projects.add_parser("list")
    projects.add_parser("create").add_argument("name")
    media = commands.add_parser("import", help="Copy a PCM16 WAV into a project")
    media.add_argument("project_id")
    media.add_argument("source", type=Path)
    analysis = commands.add_parser(
        "analyze", help="Analyze an imported asset and persist its job result"
    )
    analysis.add_argument("asset_id")
    backup = commands.add_parser("backup")
    backup.add_argument("project_id")
    backup.add_argument(
        "output",
        type=Path,
        help="New .nexus file; existing files are never overwritten",
    )
    recovery = commands.add_parser("restore")
    recovery.add_argument("source", type=Path)
    commands.add_parser("jobs")
    commands.add_parser("engines", help="List registered engine capabilities")
    commands.add_parser("models", help="List model installation status")
    worker = commands.add_parser(
        "worker", help="Process ready queued jobs while desktop is closed"
    )
    worker.add_argument("--limit", type=int, default=256)
    tts = commands.add_parser("tts", help="Queue local speech synthesis")
    tts.add_argument("project_id")
    source = tts.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--text-file", type=Path)
    tts.add_argument("--voice", default="af_heart")
    tts.add_argument("--language", default="en-us")
    tts.add_argument("--speed", type=float, default=1)
    tts.add_argument("--model", default="kokoro-v1")
    tts.add_argument("--wait", action="store_true")
    transcribe = commands.add_parser("transcribe", help="Queue local transcription")
    transcribe.add_argument("asset_id")
    transcribe.add_argument("--language")
    transcribe.add_argument("--model", default="whisper-tiny")
    transcribe.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    transcribe.add_argument("--wait", action="store_true")
    workflows = commands.add_parser("workflows").add_subparsers(
        dest="action", required=True
    )
    workflows.add_parser("templates")
    imp = workflows.add_parser("template-import")
    imp.add_argument("source", type=Path)
    exp = workflows.add_parser("template-export")
    exp.add_argument("template_id")
    exp.add_argument("output", type=Path)
    launch = workflows.add_parser("run")
    launch.add_argument("project_id")
    launch.add_argument("template_id")
    launch.add_argument(
        "--input",
        action="append",
        required=True,
        help="Asset UUID or text; repeat for a batch",
    )
    launch.add_argument("--request-key", default=None)
    launch.add_argument("--wait", action="store_true")
    listing = workflows.add_parser("list")
    listing.add_argument("project_id")
    listing.add_argument("--before")
    for action in ("status", "cancel", "retry"):
        command = workflows.add_parser(action)
        command.add_argument("run_id")
        if action == "retry":
            command.add_argument("--request-key", default=None)
            command.add_argument("--wait", action="store_true")
    return root


class ExecutionFailed(Exception):
    def __init__(self, result):
        self.result = result
        super().__init__("automation_failed")


def automation_dispatch(core, args):
    from .automation import drain, submit_transcription, submit_tts
    from .engines import registry
    from .models import ModelManager
    from .workflows import WorkflowService

    if args.command == "engines":
        return registry()
    models = ModelManager(core.db)
    service = WorkflowService(core, models)
    try:
        if args.command == "models":
            return models.list()
        if args.command == "worker":
            result = drain(core, models, args.limit)
            if result["failed"]:
                raise ExecutionFailed(result)
            return result
        if args.command in {"tts", "transcribe"}:
            if args.command == "tts":
                if args.text_file and args.text_file.stat().st_size > 32 * 1024:
                    raise DomainError("invalid_speech_text")
                text = (
                    args.text_file.read_text(encoding="utf-8")
                    if args.text_file
                    else args.text
                )
                result = submit_tts(
                    core,
                    models,
                    args.project_id,
                    text,
                    {
                        "model_id": args.model,
                        "voice": args.voice,
                        "language": args.language,
                        "speed": args.speed,
                    },
                )
            else:
                result = submit_transcription(
                    core,
                    models,
                    args.asset_id,
                    {
                        "model_id": args.model,
                        "language": args.language,
                        "device": args.device,
                    },
                )
            if args.wait:
                drain(core, models, job_id=result["id"])
                result = core.job(result["id"])
                if result["state"] != "completed":
                    raise ExecutionFailed(result)
            return result
        if args.action == "templates":
            return service.templates()
        if args.action == "template-import":
            if args.source.stat().st_size > 64 * 1024:
                raise DomainError("invalid_workflow_definition")
            data = json.loads(args.source.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("schema") != 1
                or set(data) - {"schema", "name", "description", "definition"}
            ):
                raise DomainError("invalid_workflow_definition")
            return service.create_template(
                data.get("name"), data.get("description", ""), data.get("definition")
            )
        if args.action == "template-export":
            template = service.template(args.template_id)
            data = {
                "schema": 1,
                "name": template["name"],
                "description": template.get("description", ""),
                "definition": template["definition"],
            }
            with args.output.open("x", encoding="utf-8") as output:
                output.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            return {"template_id": template["id"], "output": str(args.output)}
        if args.action == "list":
            return service.list_runs(args.project_id, args.before)
        if args.action == "status":
            return service.run(args.run_id)
        if args.action == "cancel":
            return service.cancel(args.run_id)
        key = args.request_key or str(uuid.uuid4())
        result = (
            service.retry(args.run_id, key)
            if args.action == "retry"
            else service.start(args.project_id, args.template_id, args.input, key)
        )
        if args.wait:
            drain(core, models, workflow_id=result["id"])
            result = service.run(result["id"])
            if result["state"] != "completed":
                raise ExecutionFailed(result)
        return result
    finally:
        models.close()


def dispatch(core, args):
    if args.command in {
        "engines",
        "models",
        "worker",
        "tts",
        "transcribe",
        "workflows",
    }:
        return automation_dispatch(core, args)
    if args.command == "projects":
        return (
            core.projects() if args.action == "list" else core.create_project(args.name)
        )
    if args.command == "import":
        return core.import_file(args.project_id, args.source)
    if args.command == "jobs":
        return core.jobs()
    if args.command == "restore":
        return restore(core, args.source)
    if args.command == "backup":
        # Reserve destination before making a snapshot; never replace user data.
        with args.output.open("xb") as destination:
            try:
                backup = create(core, args.project_id)
                source = core.db.root / "backups" / (backup["id"] + ".nexus")
                with source.open("rb") as stream:
                    shutil.copyfileobj(stream, destination)
            except BaseException:
                destination.close()
                args.output.unlink(missing_ok=True)
                raise
        return backup
    if args.command == "analyze":
        from .core import now

        job = core.create_job(args.asset_id)
        with core.db.connect() as db:
            db.execute("UPDATE jobs SET state='running' WHERE id=?", (job["id"],))
        try:
            result = analyze(
                core.asset_path(args.asset_id), lambda _: None, lambda: False
            )
            with core.db.connect() as db:
                db.execute(
                    "UPDATE jobs SET state='completed',progress=1,result=?,updated=? WHERE id=?",
                    (json.dumps(result), now(), job["id"]),
                )
        except BaseException:
            with core.db.connect() as db:
                db.execute(
                    "UPDATE jobs SET state='interrupted',updated=? WHERE id=?",
                    (now(), job["id"]),
                )
            raise
        return core.job(job["id"])
    raise DomainError("unknown_command")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        with workspace_lock(args.data_dir):
            result = dispatch(Core(args.data_dir), args)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except ExecutionFailed as exc:
        print(
            json.dumps(
                {"ok": False, "error": "automation_failed", "result": exc.result}
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        error, code = "interrupted", 130
    except (ValueError, MediaError, NotFound) as exc:
        error, code = str(exc), 1
    except RuntimeError as exc:
        error = (
            "workspace_in_use"
            if str(exc) == "workspace_in_use"
            else "workspace_unavailable"
        )
        code = 1
    except FileExistsError:
        error, code = "output_exists", 1
    except OSError:
        error, code = "io_error", 1
    print(json.dumps({"ok": False, "error": error}), file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
