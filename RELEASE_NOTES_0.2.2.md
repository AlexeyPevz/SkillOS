## SkillOS v0.2.2

### Fixed
- Postgres budget usage transaction now uses a proper context manager, unblocking budget checks in pipelines and compositions.
- Postgres job store no longer returns from `save()` and now exposes `list_all()`, fixing job worker and webhook processing.

### Notes
- Test suite: 161 passed, 1 skipped.
