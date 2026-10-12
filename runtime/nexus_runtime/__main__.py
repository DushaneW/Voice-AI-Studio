"""Packaged process entry point; stdin supplies token, stdout emits one handshake."""

import json
import os
import socket
import sys
import threading
from pathlib import Path

import uvicorn

from .api import create_app
from .locking import workspace_lock


def self_test(require_ai=False):
    import importlib
    import tempfile

    from . import VERSION
    from .models import CATALOG

    with tempfile.TemporaryDirectory(prefix="nexus-self-test-") as temporary:
        app = create_app(Path(temporary), "self-test-" + "x" * 40)
        project = app.state.core.create_project("Packaging check")
        assert project["name"] == "Packaging check"
        from .auditlog import close

        close()
        assert {"kokoro-v1", "whisper-tiny"} <= {model["id"] for model in CATALOG}
    if require_ai:
        for module in (
            "faster_whisper",
            "ctranslate2",
            "kokoro_onnx",
            "onnxruntime",
            "av",
        ):
            importlib.import_module(module)
    return {
        "ok": True,
        "version": VERSION,
        "catalog_models": len(CATALOG),
        "ai_imports_checked": require_ai,
    }


def watch_parent(stream, server, stopped, grace_seconds=50):
    """EOF means the owning desktop process exited; release the workspace lock.

    Graceful shutdown is preferred. A native inference call can ignore cancellation,
    so the process has a bounded exit deadline even when Python cannot join it.
    """
    try:
        while stream.read(1):
            pass
    finally:
        server.should_exit = True
        if not stopped.wait(grace_seconds):
            os._exit(1)


def main():
    if "--self-test" in sys.argv[1:]:
        print(json.dumps(self_test("--require-ai" in sys.argv[1:])))
        return
    token = sys.stdin.readline(256).strip()
    root = Path(os.environ["NEXUS_DATA_DIR"])
    with workspace_lock(root):
        from .hygiene import cleanup

        cleanup(root)
        app = create_app(root, token)
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.bind(("127.0.0.1", 0))
        connection.listen(128)
        port = connection.getsockname()[1]
        print(json.dumps({"port": port, "api_version": "1"}), flush=True)
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", access_log=False)
        )
        app.state.shutdown = lambda: setattr(server, "should_exit", True)
        stopped = threading.Event()
        threading.Thread(
            target=watch_parent,
            args=(sys.stdin, server, stopped),
            daemon=True,
            name="nexus-parent-watchdog",
        ).start()
        try:
            server.run(sockets=[connection])
        finally:
            stopped.set()
            connection.close()


if __name__ == "__main__":
    main()
