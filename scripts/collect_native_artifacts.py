"""Collect genuine native build outputs; diagnostic core-only builds cannot pass."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import tomllib

TARGETS = {
    "x86_64-unknown-linux-gnu": (".deb", ".AppImage"),
    "x86_64-pc-windows-msvc": (".exe", ".msi"),
    "x86_64-apple-darwin": (".dmg",),
    "aarch64-apple-darwin": (".dmg",),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    host = next(
        line.split(": ", 1)[1]
        for line in subprocess.check_output(["rustc", "-vV"], text=True).splitlines()
        if line.startswith("host:")
    )
    if host != args.target:
        raise SystemExit("Native host and target do not match")
    report = json.loads((root / "build/runtime/package-verification.json").read_text())
    if report.get("core_only") is not False or not report.get("self_test", {}).get("ok"):
        raise SystemExit("AI runtime verification missing")
    files = [
        p
        for p in (root / "target/release/bundle").rglob("*")
        if p.is_file() and p.suffix in TARGETS[args.target]
    ]
    if any(
        not any(p.suffix == suffix for p in files) for suffix in TARGETS[args.target]
    ):
        raise SystemExit("Expected installer format missing")
    output = root / "build/native-candidate" / args.target
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise SystemExit("Output is not empty; use a clean build")
    records = []
    for source in files:
        target = output / source.name
        if target.exists():
            raise SystemExit("Installer filename collision")
        shutil.copy2(source, target)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        records.append(
            {"name": target.name, "size": target.stat().st_size, "sha256": digest}
        )
    version = tomllib.loads((root / "runtime/pyproject.toml").read_text())["project"][
        "version"
    ]
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "target": args.target,
                "version": version,
                "signed": False,
                "status": "unsigned candidate; physical acceptance pending",
                "installers": records,
            },
            indent=2,
        )
        + "\n"
    )
    shutil.copy2(root / "docs/PLATFORM_BUILDS.md", output / "INSTALL.md")


if __name__ == "__main__":
    main()
