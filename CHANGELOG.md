# Changelog

## Unreleased

### Added
- Model catalog: Whisper Base, Small and Medium (faster-whisper, pinned Hugging Face
  revisions, SHA-256 verified), next to Whisper Tiny.
- Transcription and settings model pickers show download size, install state and a
  speed/accuracy hint. Without a saved preference the first installed Whisper model
  is selected instead of the first catalog entry.

### Changed
- `scripts/verify_ai.py` installs only the models it exercises (Kokoro, Whisper Tiny).
- Runtime: expected failures use `DomainError` (stable code, HTTP 409) and
  `NotFound` (404) from `nexus_runtime/errors.py`. A plain `ValueError` is now a
  defect: HTTP 500 `internal_error`, logged by exception class only. Previously
  every `ValueError` was reported as a 409 conflict.
- Inference engines are cached per (engine, model path, device) and dropped on
  model uninstall/repair and runtime shutdown. Models are no longer reloaded per job.
- Speech synthesis splits text into sentence chunks, reports progress per chunk and
  honours cancellation between chunks.
- Job queue has two lanes: model operations and media jobs. A media job still waits
  for a queued or running operation on the same model.
- Schema migrations moved to `nexus_runtime/migrations.py` as an ordered list.
- Frontend translations split into `app/i18n/{en,pl,index}.ts`, with tests that fail
  on untranslated Polish keys and mismatched placeholders.
- Workflows, audiobook and dubbing screens hidden unless built with
  `VITE_NEXUS_EXPERIMENTAL=1`.
- README: added home and settings screenshots (`docs/images/`).
- Documentation: per-feature progress reports, checkpoint reports and the original
  specifications moved to `docs/archive/`; README rewritten to separate tested from
  unverified behaviour.

### Tests
- Python 175 -> 193; frontend 86 -> 93 (counts from one local run; native Rust tests
  were not run in that environment).

## 0.1.0 (development preview)
Initial runtime, desktop shell, jobs, models, transcripts, timeline, backups, CLI.
Earlier per-checkpoint details: `docs/archive/`.
