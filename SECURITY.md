# Security

Runtime binds IPv4 loopback on an OS-assigned port. Rust generates a random
256-bit bearer token, passes it on stdin and keeps it out of frontend state.
Requests with browser Origin headers are rejected. The frontend uses restricted
Tauri commands; arbitrary methods, external URLs and import paths are not exposed
through the generic proxy. Native dialogs authorize file selection.

The runtime does not execute user-provided shell commands. Media is copied into
managed storage and validated before database registration. UUIDs name stored files.
Model downloads occur only after an explicit installation action and use a pinned
catalog with exact sizes and SHA-256 verification. Audio is processed locally.
The runtime sets telemetry opt-out variables before optional engine imports and
explicitly disables ONNX telemetry. No cloud audio upload is implemented.

An OS-owned workspace lock prevents desktop and CLI processes from concurrently
recovering or modifying the same database. The lock is released on process exit,
including crashes. Backups reject unexpected ZIP entries, duplicate paths and
checksum mismatches; restoration creates fresh project, asset and transcript IDs.

This is a development preview, not a security-audited release. Local malware
running as the same OS user is outside this isolation boundary. Imports are not
sandboxed; a dedicated media worker and stronger resource limits are planned.

Report suspected vulnerabilities privately to the repository owner through
GitHub private vulnerability reporting when enabled. Do not attach real audio.

## Editor and archive integrity update

Transcript times and document structures are validated in the shared domain layer,
including backup restoration. Unchanged segment word timing is preserved;
edited alignment is explicitly invalidated. Backup creation reads a consistent
SQLite metadata snapshot and verifies size/SHA-256 while streaming assets.
Failed/cancelled worker outputs are cleaned up during normal exception handling.
This is not a durable transaction across a process crash.

Diagnostic job failures use bounded rotating JSONL files under workspace/logs.
They contain timestamps, job identifiers, known job kinds and exception class,
not exception messages, user text or audio paths. Unsaved editor guards protect
normal navigation/closing; forced termination still requires explicit saved work.
