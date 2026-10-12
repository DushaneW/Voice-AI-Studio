# NEXUS

Local-first audio workspace: projects and WAV management, local Kokoro speech
synthesis, Whisper transcription, timeline mixing and subtitle export. Recordings
stay on your machine; there is no telemetry. Stack: React + Tauri + Rust supervisor
+ Python/FastAPI runtime. UI languages: English, Polski.

![NEXUS home screen](docs/images/nexus-home.png)

*Home screen of the native window.*

![NEXUS settings](docs/images/nexus-settings.png)

*Settings and workspace configuration.*

## Features

- Projects: create, rename, favorites, search, recoverable trash.
- WAV import/export with managed copies and SHA-256; PCM16 analysis (peaks, RMS in dBFS).
- Durable SQLite job queue with cancel, retry and interrupted-job recovery. Model
  downloads and media jobs run in separate lanes; one inference runs at a time.
- Pinned, checksum-verified model install with pause/resume/verify/uninstall.
- Speech synthesis (Kokoro, CPU) and transcription (Whisper tiny) through cached
  engines; synthesis is split into chunks so cancel takes effect between chunks.
- Transcript editing with revision checks, speakers, SRT/VTT import, TXT/SRT/VTT/JSON export.
- Multitrack timeline render to WAV (24/44.1/48 kHz, mono or stereo).
- Portable backup/restore with checksums; offline CLI.
- Authenticated loopback runtime, Rust process ownership, restricted IPC proxy.

Workflows, audiobooks and dubbing can be enabled in the UI by building with
`VITE_NEXUS_EXPERIMENTAL=1`.

## Development

Requirements: Python 3.11+, Node 22+, stable Rust and the platform
[Tauri prerequisites](https://tauri.app/start/prerequisites/). Use a path without
spaces or parentheses.

~~~sh
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
python -m pip install -e "./runtime[ai,test]"
cd apps/desktop
npm ci
npm run desktop
~~~

CLI: `nexus --data-dir /path/to/workspace projects list` (close the desktop
app first; see [CLI](docs/CLI.md)).

## Verify

~~~sh
python -m ruff check runtime && python -m ruff format --check runtime
python -m pytest runtime/tests -q
cargo fmt --all -- --check
cargo clippy -p nexus-supervisor -- -D warnings
NEXUS_TEST_PYTHON="$(command -v python)" cargo test -p nexus-supervisor -- --include-ignored
cd apps/desktop && npm run lint && npm test && npm run build
~~~

## Native bundle

~~~sh
python -m pip install pyinstaller
python scripts/package_runtime.py
cd apps/desktop && npm run tauri build
~~~

Build on each target OS. See [platform builds](docs/PLATFORM_BUILDS.md).

## Technical specs

WAV PCM16, plus MP3/M4A/FLAC/OGG/AAC when FFmpeg is installed; 512 MiB import limit,
32 MiB in-app playback limit. Timeline: up to 64 clips, 32 tracks, 1 hour.
Deleting a project or asset moves it to trash; nothing is purged automatically.

## More

[Architecture](ARCHITECTURE.md) · [Security](SECURITY.md) · [User guide](docs/USER_GUIDE.md) ·
[Models](docs/MODELS.md) · [Roadmap](docs/ROADMAP.md) · [Changelog](CHANGELOG.md) ·
[Contributing](CONTRIBUTING.md)

Version source: `runtime/pyproject.toml`; run `python scripts/sync_version.py`
after changing it. No model weights are bundled. MIT © DushaneW
