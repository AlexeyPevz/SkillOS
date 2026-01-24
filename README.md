# SkillOS MVP

Initial scaffold for SkillOS development.

## CLI

- `poetry run skillos add-skill travel/search_flights --root ./skills`
- `poetry run skillos add-connector weather_api --type http --root ./skills`
- `poetry run skillos compose-skill travel/plan_trip --root ./skills --step travel/search_flights --step travel/build_itinerary`
- `poetry run skillos compose-skill travel/plan_trip --root ./skills --step travel/search_flights|travel/search_hotels`
- `poetry run skillos activate-skill travel/plan_trip --root ./skills --approval approved`
- `poetry run skillos run-skill travel/search_flights --root ./skills`
- `poetry run skillos run "Find flights to Sochi" --root ./skills`
- `poetry run skillos run "Find flights to Sochi" --root ./skills --mode pipeline`
- `poetry run skillos run "Find flights to Sochi" --root ./skills --mode parallel`
- `poetry run skillos run "Find flights to Sochi" --root ./skills --tag travel`
- `poetry run skillos run "Delete records" --root ./skills --execute --approval approved`
- `poetry run skillos run "Delete records" --root ./skills --execute --dry-run --plan-path ./plan.json`
- `poetry run skillos run "Delete records" --root ./skills --execute --approval approved --plan-path ./plan.json`
- `poetry run skillos run "List users" --root ./skills --execute --role admin`
- `poetry run skillos run "Find flights to Sochi" --root ./skills --debug --profile --trace`
- `poetry run skillos run "Find flights to Sochi" --root ./skills --step-through`
- `poetry run skillos run "Find flights to Sochi" --root ./skills --jwt "<token>"`
- `poetry run skillos feedback travel.build_itinerary --expected-skill-id travel.search_flights --root ./skills`
- `poetry run skillos schedule add travel/search_flights --run-at 2026-01-18T08:00:00+03:00 --root ./skills`
- `poetry run skillos schedule tick --root ./skills`
- `poetry run skillos job enqueue travel/search_flights --root ./skills --payload "ok" --max-retries 2`
- `poetry run skillos job work --root ./skills`
- `poetry run skillos pipeline run --root ./skills --step ops/first --step ops/second --payload "start"`
- `poetry run skillos pipeline run --root ./skills --step-through --step ops/first --step ops/second --payload "start"`
- `poetry run skillos webhook handle --id sample-hook --path ./payload.json --signature "t=...,v1=..." --root ./skills`
- `poetry run skillos metrics --root ./skills --golden tests/fixtures/golden_queries.json`
- `poetry run skillos test travel/search_flights --root ./skills`
- `poetry run skillos validate --root ./skills`
- `poetry run skillos deprecate-skill travel/search_flights --reason "use travel/search_hotels" --replacement travel/search_hotels --root ./skills`
- `poetry run skillos undeprecate-skill travel/search_flights --root ./skills`
- `poetry run skillos optimize travel/search_flights --variant v1 --variant v2 --result v1:success --result v2:failure --root ./skills`
- `poetry run skillos marketplace browse --catalog tests/fixtures/marketplace/catalog.json --tag greeting`
- `poetry run skillos marketplace show community/hello --catalog tests/fixtures/marketplace/catalog.json`
- `poetry run skillos marketplace install community/hello --root ./skills --catalog tests/fixtures/marketplace/catalog.json`

## Release

- `poetry run pytest`
- `powershell -ExecutionPolicy Bypass -File scripts/smoke_v1.ps1`
- `powershell -ExecutionPolicy Bypass -File scripts/smoke_postgres.ps1`
- See `RELEASE_CHECKLIST.md`

## Go-live (production)

- Set `SKILLOS_ROOT` to the skills directory (shared across CLI/API).
- Choose storage backend:
  - `SKILLOS_STORAGE_BACKEND=postgres` (recommended) or omit for file storage.
  - Set `SKILLOS_POSTGRES_DSN` (or `DATABASE_URL`) and optional `SKILLOS_POSTGRES_SCHEMA`.
  - Tables are auto-created on first use.
- Configure security and policies:
  - Approval token: `SKILLOS_APPROVAL_TOKEN` and `policies/approval_policies.json`.
  - Permissions: `policies/permission_policies.json` and use `--role` / JWT roles.
  - JWT: `SKILLOS_JWT_*` if using API auth.
- Webhooks and caching (if used):
  - `SKILLOS_WEBHOOK_SECRET` for signature checks.
  - `SKILLOS_CACHE_ENABLED=1` and `SKILLOS_REDIS_URL` for cache/redis.
- Run checks before cutover:
  - `poetry run pytest`
  - `powershell -ExecutionPolicy Bypass -File scripts/smoke_postgres.ps1`
- Start API server: `poetry run uvicorn skillos.api:app --host 0.0.0.0 --port 8000`

## API

- `GET /health`
- `POST /run` with `{ "query": "...", "execute": false }`
- `POST /validate` with `{ "check_entrypoints": true }`
- `POST /skills/{id}/deprecate` with `{ "reason": "...", "replacement_id": "..." }`
- `POST /skills/{id}/undeprecate`

Use `Authorization: Bearer <token>` for JWT auth.
Handlers are async; blocking work runs in the thread pool (CLI stays sync).

## Attachments

Webhook payloads can include attachments with base64-encoded content. Files are
stored under `{skills_root}/attachments`, and skills receive metadata plus a
file reference.

Example payload:

```
{
  "payload": "hello",
  "attachments": [
    {
      "filename": "image.png",
      "content_type": "image/png",
      "data": "<base64>"
    }
  ]
}
```

Attachment limits can be tuned via:

- `SKILLOS_ATTACHMENT_MAX_SIZE_BYTES` (default: 10485760)

## Composition

Parallel groups can be defined by separating skill ids with `|` inside a
`--step` value. Use `SKILLOS_PARALLEL_LIMIT` to cap concurrent steps
(default: 4).

## Connectors

Connector definitions live under `connectors/` in the skill root. Reference secrets
with `secret:KEY` values; they resolve from environment variables or
`secrets/.env` at runtime.

## Budget controls

Budget checks for routing can be tuned with environment variables:

- `SKILLOS_BUDGET_PER_REQUEST` (default: 5)
- `SKILLOS_BUDGET_DAILY` (default: 50)
- `SKILLOS_BUDGET_MONTHLY` (default: 200)
- `SKILLOS_BUDGET_LOW_REMAINING` (default: 10)
- `SKILLOS_MODEL_STANDARD_COST` (default: 1)
- `SKILLOS_MODEL_CHEAP_COST` (default: 0.5)

## Idempotency controls

- `SKILLOS_IDEMPOTENCY_TTL_SECONDS` (default: 300)

## Webhook controls

- `SKILLOS_WEBHOOK_SECRET` (HMAC secret for webhook signatures)
- `SKILLOS_WEBHOOK_ALLOW_UNSIGNED` (set to 1 to accept unsigned webhooks)

## Rate limit controls

- `SKILLOS_RATE_LIMIT_ENABLED` (default: 1)
- `SKILLOS_RATE_LIMIT_REQUESTS` (default: 60)
- `SKILLOS_RATE_LIMIT_WINDOW_SECONDS` (default: 60)
- `SKILLOS_RATE_LIMIT_STRICT` (set to 1 to require Redis + atomic limiter)

## Approval controls

High-risk operations require approval when executing. Approval policies can be
defined per skill in `policies/approval_policies.json` under the skill root:

```
{
  "policies": [
    {"skill_id": "finance/close_books", "requires_approval": true}
  ]
}
```

If `SKILLOS_APPROVAL_TOKEN` is set, `--approval-token` must match it to approve.

## Permission controls

Role-based permissions can be configured per skill in
`policies/permission_policies.json` under the skill root:

```
{
  "roles": {
    "admin": ["admin:read", "admin:write"],
    "viewer": ["admin:read"]
  },
  "policies": [
    {"skill_id": "admin/*", "required_permissions": ["admin:read"]},
    {"skill_id": "admin/delete_records", "required_permissions": ["admin:write"]}
  ]
}
```

Use `--role` on `skillos run` to supply the executing role.
