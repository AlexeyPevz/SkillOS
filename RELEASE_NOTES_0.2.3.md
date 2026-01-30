## SkillOS v0.2.3

### Fixed
- Postgres budget usage transaction now uses a proper context manager, unblocking budget checks in pipelines and compositions.
- Postgres job store no longer returns from `save()` and now exposes `list_all()`, fixing job worker and webhook processing.
- Postgres test isolation uses per-test tenant ids to avoid cross-test collisions.
- Tests now use backend-aware stores for suggestions, schedules, and webhooks.

### Notes
- Test suite: 161 passed, 1 skipped.
