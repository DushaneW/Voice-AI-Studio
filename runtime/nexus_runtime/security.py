"""Inspectable runtime policy without secrets or project content."""

import os
import stat
from urllib.parse import urlsplit


def report(core, models):
    entries = []
    for name in ("assets", "models", "cache", "backups", "logs", "nexus.sqlite3"):
        path = core.db.root / name
        try:
            info = path.lstat()
            entries.append(
                {
                    "name": name,
                    "exists": True,
                    "symlink": stat.S_ISLNK(info.st_mode),
                    "private": not bool(stat.S_IMODE(info.st_mode) & 0o077)
                    if os.name == "posix"
                    else None,
                }
            )
        except FileNotFoundError:
            entries.append(
                {"name": name, "exists": False, "symlink": False, "private": None}
            )
    mode = stat.S_IMODE(core.db.root.stat().st_mode) if os.name == "posix" else None
    return {
        "api": {
            "authentication": "bearer",
            "browser_origins": "rejected",
            "packaged_bind": "127.0.0.1",
        },
        "workspace": {
            "private": mode & 0o077 == 0 if mode is not None else None,
            "permissions_scope": "posix_mode"
            if os.name == "posix"
            else "acl_not_inspected",
            "entries": entries,
        },
        "models": [
            {"id": model["id"], "state": model["state"], "error": model["error"]}
            for model in models.list()
        ],
        "model_verification": "sha256_on_install_or_explicit_verify",
    }


def privacy(core, models):
    hosts = sorted(
        {
            urlsplit(file["url"]).hostname
            for model in models.catalog.values()
            for file in model["files"]
            if urlsplit(file["url"]).hostname
        }
    )
    return {
        "processing": "local",
        "cloud_providers": [],
        "telemetry": "not_implemented",
        "model_downloads_allowed": core.db.settings().get(
            "model_downloads_allowed", True
        ),
        "active_model_operations": core.db.rows(
            "SELECT id,state FROM models WHERE state IN ('downloading','verifying')"
        ),
        "catalog_download_hosts": hosts,
        "network_scope": "model_downloader_only",
        "system_network_monitoring": False,
    }
