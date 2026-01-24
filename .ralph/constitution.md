# Constitution

Core behavior:
- Use PRD_RALPH.json as the source of truth.
- One story per iteration; no scope creep.
- Tests are the gate; fix failures before moving on.

Editing rules:
- Prefer `rg` for search.
- Prefer `apply_patch` for single-file edits.
- Default to ASCII; avoid adding new Unicode unless required.
- Do not revert unrelated changes or use destructive git commands.

Output:
- Keep changes minimal and focused.
- Update .ralph/progress.md each iteration.
