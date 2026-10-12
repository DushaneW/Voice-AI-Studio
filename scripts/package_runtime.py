"""Package the runtime, explicitly collect resources, and verify the executable.

Default builds require the AI engines. --core-only is a diagnostic build, not
an AI-capable release. Without rustc the verified binary stays in build/runtime/dist.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

AI_MODULES = ("faster_whisper", "ctranslate2", "kokoro_onnx", "onnxruntime", "av")


def command(root, work, core_only):
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "nexus-runtime",
        "--paths",
        str(root / "runtime"),
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work),
        "--collect-all",
        "nexus_runtime",
        "--collect-all",
        "uvicorn",
    ]
    if not core_only:
        for module in AI_MODULES:
            args.extend(["--collect-all", module])
    args.append(str(root / "scripts" / "runtime_entry.py"))
    return args


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.core_only:
        missing = [module for module in AI_MODULES if find_spec(module) is None]
        if missing:
            parser.error(
                "Install runtime[ai] before packaging; missing: " + ", ".join(missing)
            )
    root = Path(__file__).resolve().parents[1]
    work = root / "build" / "runtime"
    subprocess.run(command(root, work, args.core_only), check=True, cwd=root)
    suffix = ".exe" if os.name == "nt" else ""
    binary = work / "dist" / ("nexus-runtime" + suffix)
    result = subprocess.run(
        [str(binary), "--self-test", *(["--require-ai"] if not args.core_only else [])],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    report = json.loads(result.stdout)
    if report.get("ok") is not True:
        raise RuntimeError("Packaged runtime self-test failed")
    destination = None
    if not args.core_only and shutil.which("rustc"):
        version = subprocess.check_output(["rustc", "-vV"], text=True)
        target = next(
            line.split(": ", 1)[1]
            for line in version.splitlines()
            if line.startswith("host:")
        )
        destination = (
            root
            / "apps"
            / "desktop"
            / "src-tauri"
            / "binaries"
            / ("nexus-runtime-" + target + suffix)
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, destination)
    summary = {
        "binary": str(binary),
        "sidecar": str(destination) if destination else None,
        "core_only": args.core_only,
        "self_test": report,
    }
    (work / "package-verification.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
