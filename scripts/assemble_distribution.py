"""Require all platforms before assembling full source, docs and installers."""

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import tomllib
from collect_native_artifacts import TARGETS


def main():
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "runtime/pyproject.toml").read_text())["project"][
        "version"
    ]
    files = []
    for target in TARGETS:
        directory = root / "build/downloaded-native" / f"nexus-{target}"
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest["target"] != target or manifest["version"] != version:
            raise SystemExit("Platform/version mismatch")
        records = manifest["installers"]
        if any(
            not any(Path(record["name"]).suffix == suffix for record in records)
            for suffix in TARGETS[target]
        ):
            raise SystemExit("Incomplete installer formats")
        for record in records:
            name = record["name"]
            if Path(name).name != name or "\\" in name or name in (".", ".."):
                raise SystemExit("Invalid installer filename")
            file = directory / name
            with file.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if file.stat().st_size != record["size"] or digest != record["sha256"]:
                raise SystemExit("Installer checksum mismatch")
            files.append((file, f"platforms/{target}/{name}"))
        files.extend(
            (directory / name, f"platforms/{target}/{name}")
            for name in ["manifest.json", "INSTALL.md"]
        )
    output = root / "build/distribution"
    output.mkdir(parents=True, exist_ok=True)
    source = output / f"nexus-{version}-source.zip"
    docs = output / f"nexus-{version}-documentation.zip"
    subprocess.run(
        [
            "git",
            "archive",
            "--format=zip",
            "--prefix=nexus/",
            f"--output={source}",
            "HEAD",
        ],
        cwd=root,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "archive",
            "--format=zip",
            "--prefix=nexus-documentation/",
            f"--output={docs}",
            "HEAD",
            "docs",
            "README.md",
            "ARCHITECTURE.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "LICENSE",
        ],
        cwd=root,
        check=True,
    )
    complete = output / f"nexus-{version}-all-platforms.zip"
    with zipfile.ZipFile(complete, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, source.name)
        archive.write(docs, docs.name)
        archive.write(root / "docs/PLATFORM_BUILDS.md", "START-HERE.md")
        for file, name in files:
            archive.write(file, name)
    with complete.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {complete.name}\n")


if __name__ == "__main__":
    main()
