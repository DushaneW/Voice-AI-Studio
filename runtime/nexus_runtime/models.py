"""Pinned, hash-verified model downloads with durable pause/resume state."""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import urllib.request
from pathlib import Path

from . import VERSION
from .database import Database
from .engines.cache import CACHE
from .errors import DomainError

CATALOG = json.loads(Path(__file__).with_name("catalog.json").read_text())


class ModelManager:
    def __init__(self, db: Database, catalog=None):
        self.db = db
        self.catalog = {m["id"]: m for m in (CATALOG if catalog is None else catalog)}
        self.root = db.root / "models"
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        with db.connect() as conn:
            conn.execute(
                "UPDATE models SET state='paused' WHERE state IN ('downloading','verifying')"
            )
            for identifier in self.catalog:
                conn.execute(
                    "INSERT OR IGNORE INTO models(id,state) VALUES(?,'available')",
                    (identifier,),
                )

    def require(self, identifier):
        if identifier not in self.catalog:
            raise DomainError("model_not_found")
        return self.catalog[identifier]

    def list(self):
        states = {r["id"]: r for r in self.db.rows("SELECT * FROM models")}
        jobs = {}
        for row in self.db.rows(
            "SELECT id,state,options FROM jobs WHERE kind='model_operation' ORDER BY created DESC,id DESC LIMIT 200"
        ):
            jobs.setdefault(json.loads(row["options"])["model_id"], row)
        return [
            {
                **m,
                **states[identifier],
                "size": sum(f["size"] for f in m["files"]),
                "job_id": jobs.get(identifier, {}).get("id"),
                "job_state": jobs.get(identifier, {}).get("state"),
            }
            for identifier, m in self.catalog.items()
        ]

    def state(self, identifier, state, error=None):
        with self.db.connect() as db:
            db.execute(
                "UPDATE models SET state=?,error=? WHERE id=?",
                (state, error, identifier),
            )

    def directory(self, identifier):
        self.require(identifier)
        row = self.db.rows("SELECT state FROM models WHERE id=?", (identifier,))[0]
        if row["state"] != "installed":
            raise DomainError("model_not_installed")
        return self.root / identifier

    def action(self, identifier, action):
        model = self.require(identifier)
        with self.lock:
            current = self.db.rows(
                "SELECT state FROM models WHERE id=?", (identifier,)
            )[0]["state"]
            if action in {"pause", "cancel"}:
                if current not in {"downloading", "verifying", "paused", "failed"}:
                    raise DomainError("model_not_downloading")
                self.state(identifier, "paused" if action == "pause" else "cancelled")
                return
            if self.thread and self.thread.is_alive():
                raise DomainError("model_operation_in_progress")
            if action == "uninstall":
                if self.db.rows(
                    "SELECT id FROM jobs WHERE state IN ('queued','running')"
                ):
                    raise DomainError("active_jobs")
                folder = self.root / identifier
                if folder.exists():
                    shutil.rmtree(folder)
                CACHE.invalidate(folder)
                self.state(identifier, "available")
                with self.db.connect() as db:
                    db.execute(
                        "UPDATE models SET downloaded=0 WHERE id=?", (identifier,)
                    )
                return
            if action not in {"install", "resume", "repair", "verify"}:
                raise DomainError("invalid_model_action")
            if action in {"install", "resume", "repair"} and not self.db.settings().get(
                "model_downloads_allowed", True
            ):
                raise DomainError("model_downloads_disabled")
            if action == "verify" and current != "installed":
                raise DomainError("model_not_installed")
            needed = sum(f["size"] for f in model["files"])
            if (
                action != "verify"
                and shutil.disk_usage(self.root).free < needed + 32 * 1024 * 1024
            ):
                raise DomainError("insufficient_storage")
            with self.db.connect() as db:
                db.execute(
                    "UPDATE models SET state=?,downloaded=0,error=NULL WHERE id=?",
                    ("verifying" if action == "verify" else "downloading", identifier),
                )
            self.thread = threading.Thread(
                target=self._run,
                args=(identifier, action == "verify"),
                daemon=True,
                name="nexus-models",
            )
            self.thread.start()

    def _active(self, identifier):
        if self.stop.is_set():
            raise InterruptedError
        state = self.db.rows("SELECT state FROM models WHERE id=?", (identifier,))[0][
            "state"
        ]
        if state == "downloading" and not self.db.settings().get(
            "model_downloads_allowed", True
        ):
            self.state(identifier, "paused")
            raise InterruptedError
        if state not in {"downloading", "verifying"}:
            raise InterruptedError

    def _valid(self, path, spec, identifier=None):
        if not path.is_file() or path.stat().st_size != spec["size"]:
            return False
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            while block := stream.read(1024 * 1024):
                if identifier is not None:
                    self._active(identifier)
                digest.update(block)
            return digest.hexdigest() == spec["sha256"]

    def _run(self, identifier, verify_only):
        folder = self.root / identifier
        try:
            if not verify_only:
                CACHE.invalidate(folder)  # files may be replaced below
            folder.mkdir(exist_ok=True)
            total = 0
            for spec in self.catalog[identifier]["files"]:
                self._active(identifier)
                target = folder / spec["name"]
                if not self._valid(target, spec, identifier):
                    if verify_only:
                        raise DomainError("model_checksum_mismatch")
                    partial = target.with_suffix(target.suffix + ".part")
                    offset = partial.stat().st_size if partial.exists() else 0
                    if offset == spec["size"] and self._valid(
                        partial, spec, identifier
                    ):
                        partial.replace(target)
                        total += spec["size"]
                        with self.db.connect() as db:
                            db.execute(
                                "UPDATE models SET downloaded=? WHERE id=?",
                                (total, identifier),
                            )
                        continue
                    if offset >= spec["size"]:
                        partial.unlink()
                        offset = 0
                    headers = {"User-Agent": f"NEXUS/{VERSION}"}
                    if offset:
                        headers["Range"] = "bytes=" + str(offset) + "-"
                    self._active(identifier)
                    req = urllib.request.Request(spec["url"], headers=headers)
                    with urllib.request.urlopen(req, timeout=30) as response:
                        if response.status != 206:
                            offset = 0
                        elif not response.headers.get("Content-Range", "").startswith(
                            "bytes " + str(offset) + "-"
                        ):
                            raise DomainError("model_invalid_range")
                        with partial.open("ab" if offset else "wb") as stream:
                            while block := response.read(1024 * 1024):
                                self._active(identifier)
                                offset += len(block)
                                if offset > spec["size"]:
                                    raise DomainError("model_size_mismatch")
                                stream.write(block)
                                with self.db.connect() as db:
                                    db.execute(
                                        "UPDATE models SET downloaded=? WHERE id=?",
                                        (total + offset, identifier),
                                    )
                    if not self._valid(partial, spec, identifier):
                        partial.unlink(missing_ok=True)
                        raise DomainError("model_checksum_mismatch")
                    partial.replace(target)
                total += spec["size"]
                with self.db.connect() as db:
                    db.execute(
                        "UPDATE models SET downloaded=? WHERE id=?", (total, identifier)
                    )
            self._active(identifier)
            self.state(identifier, "installed")
        except InterruptedError:
            if self.stop.is_set():
                self.state(identifier, "paused")
        except Exception as exc:  # noqa: BLE001 - download boundary; no URLs or paths in persisted errors
            code = (
                str(exc)
                if isinstance(exc, DomainError) and str(exc).startswith("model_")
                else "model_download_failed"
            )
            self.state(identifier, "failed", code)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=35)
