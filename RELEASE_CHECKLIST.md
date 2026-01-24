# Release Checklist (v1)

- [x] Run unit/integration/e2e tests: `poetry run pytest`
- [x] CI pipeline green (`tests` + `tests-postgres`)
- [x] Run smoke scripts: `powershell -ExecutionPolicy Bypass -File scripts/smoke_v1.ps1`
- [x] Run Postgres smoke: `powershell -ExecutionPolicy Bypass -File scripts/smoke_postgres.ps1`
- [x] Validate skills: `poetry run skillos validate`
- [x] Verify Postgres DSN/schema reachable (`SKILLOS_STORAGE_BACKEND`, `SKILLOS_POSTGRES_DSN`, `SKILLOS_POSTGRES_SCHEMA`)
- [x] Verify Redis connectivity if cache is enabled (`SKILLOS_CACHE_ENABLED=1`, `SKILLOS_REDIS_URL`)
- [x] Verify approval/permission policies and `SKILLOS_APPROVAL_TOKEN` if required
- [x] Verify `.env.example` is up to date for required vars (storage, jwt, approvals, webhooks)
- [x] Review logs for warnings/errors during smoke run
- [x] Update `README.md`/`PRD.md`/`ROADMAP.md` if scope changed
