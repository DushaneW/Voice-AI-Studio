# NEXUS architecture

The master specification describes the product target. This source implements
local projects, managed PCM WAV assets, analysis, speech synthesis, transcription,
transcript editing, basic mixing, audiobook/dubbing composition and backups.

## Process and trust boundaries

React/TypeScript uses a typed service adapter and restricted Tauri commands.
Native dialogs select import/export paths. Rust owns the Python child, supplies
a random 256-bit secret through stdin, validates a bounded port/version handshake
and proxies allowlisted routes. The token never enters frontend state. Python
binds only IPv4 loopback and rejects browser Origin headers.

The Python entry point takes an OS-level workspace lock before schema migration
or interrupted-job recovery. Windows byte locks and POSIX flock release on process
exit; the lock file remains to preserve its identity. The CLI uses the same lock.
Rust requests graceful shutdown, then kills/waits if the child exceeds its deadline.

## Storage and execution

SQLite WAL holds projects, media metadata, jobs/options, settings, transcripts,
model state and editor documents. Short transactions and revision checks protect
edited transcripts/documents. The worker claims queued tasks in one atomic UPDATE;
a competing worker or cancellation cannot claim the same task twice.

Managed assets use UUID filenames and SHA-256. A temporary copy is validated
before registration. Project archives capture metadata in one SQLite read transaction and verify every WAV while writing it. They contain a JSON manifest plus validated WAVs;
restoration uses new IDs and remaps timeline and dubbing references. The restore
path never extracts ZIP member paths directly into the filesystem.

The model manager downloads only catalogued, pinned files and validates size/hash
before install. Partial downloads resume; complete valid partials are promoted
without a new HTTP request. Kokoro ONNX uses an explicit CPU provider. Whisper
loads local CTranslate2 weights; CUDA support is exposed but not certified here.
Telemetry opt-out is applied before optional imports.

The durable single-worker queue handles analysis, TTS, ASR, montage, audiobook and
dubbing tasks. Cancellation is cooperative, so a native inference call may finish
before cancellation is observed. Generated assets/transcripts registered by a failed or cancelled worker are rolled back. Bounded redacted JSONL events record job ID, kind and exception class. Heavy inference is not yet isolated in a separate
per-job process. Interrupted jobs remain visible and can be retried explicitly.

## Editors and automation

Timeline clips reference immutable audio with offsets, trim ranges, gain and fades.
The mixer streams 24 kHz mono PCM16 blocks instead of allocating the entire output.
Timeline edit history retains at most 100 snapshots and resets when a project loads.
Saved documents use optimistic revisions and shared domain validation. Timeline saves before rendering. Dirty editors guard navigation and normal window closing; automatic crash-recovery drafts are still pending. Transcript edits preserve word timings only for unchanged segments and mark changed alignment invalid.

Audiobooks synthesize chapters and assemble a WAV with chapter metadata. Dubbing
synthesizes edited transcript segments at their source offsets and reports overruns;
it does not automatically translate or time-stretch speech.

The offline CLI shares Core, audio analysis and backup operations. It refuses an
occupied workspace and returns JSON with defined exit codes. Desktop polling waits
for each scheduled refresh to finish, and ignores superseded results.

## Release boundary

Source tests and CPU inference evidence are recorded in docs/VERIFICATION.md.
A native release still needs platform dependency builds, packaged-engine checks,
native dialog acceptance, license review and signing. The editable Figma home is
a design artifact, not evidence that installers were tested.
