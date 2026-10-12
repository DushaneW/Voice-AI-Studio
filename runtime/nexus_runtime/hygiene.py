"""Remove only disposable files in application-owned namespaces, under the workspace lock."""

import re
import shutil
import uuid


def cleanup(root):
    backups = root / "backups"
    if backups.is_dir() and not backups.is_symlink():
        for path in backups.glob("*.nexus"):
            try:
                owned = str(uuid.UUID(path.stem)) == path.stem
            except ValueError:
                owned = False
            if owned and path.is_file() and not path.is_symlink():
                path.unlink(missing_ok=True)
    for path in root.glob("decode-*"):
        if (
            re.fullmatch(r"decode-[a-z0-9_]{8}", path.name)
            and path.is_dir()
            and not path.is_symlink()
        ):
            shutil.rmtree(path)
