"""Bounded diagnostic events without user text, filenames or exception messages."""

import json
import logging
from logging.handlers import RotatingFileHandler


def configure(root):
    logger = logging.getLogger("nexus.events")
    path = root / "logs" / "runtime.jsonl"
    path.parent.mkdir(exist_ok=True, mode=0o700)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(
        path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def job_failed(identifier, kind, exception):
    from .core import now

    logging.getLogger("nexus.events").warning(
        json.dumps(
            {
                "at": now(),
                "event": "job_failed",
                "job_id": identifier,
                "kind": kind
                if kind
                in {
                    "analyze",
                    "tts",
                    "transcribe",
                    "timeline",
                    "audiobook",
                    "dubbing",
                    "duplicate_project",
                    "validate_project",
                    "plan_repair",
                    "apply_repair",
                    "model_operation",
                }
                else "unknown",
                "exception_type": type(exception).__name__,
            }
        )
    )


def request_failed(exception_type):
    from .core import now

    logging.getLogger("nexus.events").error(
        json.dumps(
            {"at": now(), "event": "request_failed", "exception_type": exception_type}
        )
    )


def close():
    logger = logging.getLogger("nexus.events")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
