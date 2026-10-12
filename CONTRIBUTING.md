# Contributing

Use a focused pull request with the problem, behavior change and evidence.
Keep UI, native process supervision and audio core responsibilities separate.

- New persisted fields need an explicit migration and upgrade test.
- A job must reach a terminal state; cancellation is not successful completion.
- Never include user audio, local paths, tokens or model weights in issues/logs.
- Do not invent progress percentages or hardware capability indicators.
- Add regression tests for failure paths, corruption and interruption.
- Format TypeScript with Prettier, Python with Ruff and Rust with rustfmt.
- Run the verification commands from README before requesting review.

A UI-only browser test cannot certify native dialogs or packaged runtimes.
