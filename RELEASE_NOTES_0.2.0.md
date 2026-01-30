# Release Notes - v0.2.0 (2026-01-30)

## Highlights
- Session manager with persistence and API support.
- Execution kernels with session-aware skill execution.
- Eval-as-code in YAML with matchers, limits, timeouts, and result storage.

## New Features
- `session_id` support across API, orchestrator, and pipeline execution.
- Eval runner with `equals`, `contains`, `regex`, `numeric_range`, and `regex_numeric`.
- CLI: `skillos eval-skill` and optional eval gating on `add-skill`.
- API: `POST /skills/{skill_id}/eval` with optional result saving.

## Quality & Testing
- Added unit and integration tests for sessions, kernels, and evals.
- CI job for session/eval-focused tests.

## Notes
- No breaking changes intended in this release.
