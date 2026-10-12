"""Portable project snapshots, with bounded validation and no archive extraction."""

import hashlib
import json
import tempfile
import uuid
import zipfile
from pathlib import Path

from .core import now
from .errors import DomainError
from .validation import validate_segments

LIMIT = 1024 * 1024 * 1024
MANIFEST_LIMIT = 8 * 1024 * 1024
ENTRY_LIMIT = 10001


def create(core, project_id):
    # One SQLite read transaction gives all metadata the same snapshot.
    with core.db.connect() as db:
        db.execute("BEGIN")
        row = db.execute(
            "SELECT * FROM projects WHERE id=? AND id NOT IN (SELECT project_id FROM project_trash)",
            (project_id,),
        ).fetchone()
        if row is None:
            raise DomainError("project_not_found")
        project = dict(row)
        assets = [
            dict(r)
            for r in db.execute(
                "SELECT assets.*, EXISTS(SELECT 1 FROM asset_trash WHERE asset_id=assets.id) AS trashed FROM assets WHERE project_id=?",
                (project_id,),
            )
        ]
        for asset in assets:
            asset["trashed"] = bool(asset["trashed"])
        documents = [
            dict(r)
            for r in db.execute(
                "SELECT kind,content FROM documents WHERE project_id=?", (project_id,)
            )
        ]
        transcripts = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM transcripts WHERE project_id=?", (project_id,)
            )
        ]
        for transcript in transcripts:
            transcript["segments"] = json.loads(transcript["segments"])
    if sum(a["size"] for a in assets) > LIMIT:
        raise DomainError("backup_size_limit")
    manifest = {
        "version": 2,
        "project": project,
        "assets": assets,
        "documents": documents,
        "transcripts": transcripts,
    }
    _validate_manifest(manifest)
    manifest_bytes = json.dumps(manifest, allow_nan=False).encode("utf-8")
    if len(manifest_bytes) > MANIFEST_LIMIT or len(assets) + 1 > ENTRY_LIMIT:
        raise DomainError("backup_size_limit")
    folder = core.db.root / "backups"
    folder.mkdir(exist_ok=True)
    identifier = str(uuid.uuid4())
    target = folder / (identifier + ".nexus")
    temporary = target.with_suffix(".part")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("project.json", manifest_bytes)
            for asset in assets:
                path = (core.assets / asset["path"]).resolve()
                if path.parent != core.assets.resolve():
                    raise DomainError("invalid_backup")
                digest, size = hashlib.sha256(), 0
                with (
                    path.open("rb") as source,
                    archive.open("assets/" + asset["id"] + ".wav", "w") as output,
                ):
                    while block := source.read(1024 * 1024):
                        size += len(block)
                        if size > asset["size"]:
                            raise DomainError("backup_checksum_mismatch")
                        digest.update(block)
                        output.write(block)
                if size != asset["size"] or digest.hexdigest() != asset["sha256"]:
                    raise DomainError("backup_checksum_mismatch")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "id": identifier,
        "name": project["name"],
        "size": target.stat().st_size,
        "created": now(),
    }


def _validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise TypeError("invalid_backup")
    if manifest.get("version") not in (1, 2):
        raise DomainError("unsupported_backup_version")
    project = manifest.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("name"), str):
        raise TypeError("invalid_backup")
    assets = manifest.get("assets", [])
    documents = manifest.get("documents", [])
    transcripts = manifest.get("transcripts", [])
    if not all(isinstance(items, list) for items in (assets, documents, transcripts)):
        raise DomainError("invalid_backup")
    seen_assets = set()
    for asset in assets:
        if not isinstance(asset, dict):
            raise TypeError("invalid_backup")
        identifier = asset.get("id")
        if not isinstance(identifier, str) or identifier in seen_assets:
            raise DomainError("invalid_backup")
        try:
            uuid.UUID(identifier)
        except ValueError as exc:
            raise DomainError("invalid_backup") from exc
        if (
            not isinstance(asset.get("trashed", False), bool)
            or type(asset.get("size")) is not int
            or asset["size"] < 0
            or not isinstance(asset.get("name"), str)
            or not isinstance(asset.get("sha256"), str)
        ):
            raise DomainError("invalid_backup")
        seen_assets.add(identifier)
    seen_transcripts = set()
    for transcript in transcripts:
        if (
            not isinstance(transcript, dict)
            or not isinstance(transcript.get("id"), str)
            or transcript["id"] in seen_transcripts
            or transcript.get("asset_id") not in seen_assets
            or not isinstance(transcript.get("segments"), list)
            or not isinstance(transcript.get("language"), str)
        ):
            raise DomainError("invalid_backup")
        seen_transcripts.add(transcript["id"])
        validate_segments(transcript["segments"])
    seen_documents = set()
    for doc in documents:
        if (
            not isinstance(doc, dict)
            or doc.get("kind") not in {"timeline", "audiobook", "dubbing", "project"}
            or doc["kind"] in seen_documents
            or not isinstance(doc.get("content"), str)
            or not isinstance(json.loads(doc["content"]), dict)
        ):
            raise DomainError("invalid_backup")
        seen_documents.add(doc["kind"])


def _restore(core, source: Path):
    if (
        source.is_symlink()
        or not source.is_file()
        or source.stat().st_size > LIMIT + 16 * 1024 * 1024
    ):
        raise DomainError("invalid_backup")
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if (
            len(infos) > ENTRY_LIMIT
            or sum(i.file_size for i in infos) > LIMIT + 16 * 1024 * 1024
        ):
            raise DomainError("backup_size_limit")
        if len({i.filename for i in infos}) != len(infos):
            raise DomainError("invalid_backup")
        info = archive.getinfo("project.json")
        if info.file_size > MANIFEST_LIMIT:
            raise DomainError("invalid_backup")
        manifest = json.loads(archive.read(info))
        _validate_manifest(manifest)
        assets = manifest.get("assets", [])
        allowed = {"project.json"}
        for asset in assets:
            uuid.UUID(asset["id"])
            allowed.add("assets/" + asset["id"] + ".wav")
        if set(archive.namelist()) != allowed:
            raise DomainError("invalid_backup")
        project = core.create_project(manifest["project"]["name"][:109] + " (restored)")
        created = []
        try:
            mapping = {}
            with tempfile.TemporaryDirectory(
                dir=core.db.root, prefix="restore-"
            ) as temp:
                for asset in assets:
                    path = Path(temp) / (asset["id"] + ".wav")
                    digest = hashlib.sha256()
                    size = 0
                    with (
                        archive.open("assets/" + asset["id"] + ".wav") as source_stream,
                        path.open("xb") as destination,
                    ):
                        while block := source_stream.read(1024 * 1024):
                            size += len(block)
                            if size > min(asset["size"], 512 * 1024 * 1024):
                                raise DomainError("backup_size_limit")
                            digest.update(block)
                            destination.write(block)
                    if size != asset["size"] or digest.hexdigest() != asset["sha256"]:
                        raise DomainError("backup_checksum_mismatch")
                    imported = core.import_file(project["id"], path)
                    created.append(core.asset_path(imported["id"]))
                    mapping[asset["id"]] = imported["id"]
                    with core.db.connect() as db:
                        db.execute(
                            "UPDATE assets SET name=? WHERE id=?",
                            (asset["name"], imported["id"]),
                        )
            transcript_mapping = {}
            for transcript in manifest.get("transcripts", []):
                validate_segments(
                    transcript["segments"],
                    core.asset(mapping[transcript["asset_id"]])["duration"],
                )
                identifier = str(uuid.uuid4())
                transcript_mapping[transcript["id"]] = identifier
                with core.db.connect() as db:
                    db.execute(
                        "INSERT INTO transcripts(id,project_id,asset_id,segments,language,updated) VALUES(?,?,?,?,?,?)",
                        (
                            identifier,
                            project["id"],
                            mapping[transcript["asset_id"]],
                            json.dumps(transcript["segments"]),
                            transcript["language"],
                            now(),
                        ),
                    )
            for doc in manifest.get("documents", []):
                content = json.loads(doc["content"])
                if doc["kind"] == "timeline":
                    for clip in content.get("clips", []):
                        clip["asset_id"] = mapping[clip["asset_id"]]
                if doc["kind"] == "dubbing" and content.get("transcriptId"):
                    content["transcriptId"] = transcript_mapping[
                        content["transcriptId"]
                    ]
                core.save_document(project["id"], doc["kind"], content, 0)
            for asset in assets:
                if asset.get("trashed", False):
                    core.trash_asset(mapping[asset["id"]])
            return project
        except Exception:
            core.delete_project(project["id"])
            for path in created:
                path.unlink(missing_ok=True)
            raise


def restore(core, source: Path):
    try:
        return _restore(core, source)
    except (
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
        UnicodeDecodeError,
    ) as exc:
        raise DomainError("invalid_backup") from exc
