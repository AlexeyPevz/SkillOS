# Production Readiness Walkthrough

This document summarizes the changes made to bring SkillOS MVP to a production-ready state.

## 1. Security Hardening

### Attachment Limits

We introduced strict limits on attachment size and types to prevent DoS and arbitrary code execution via file uploads.

- **File**: `skillos/attachments.py`
- **Limits**:
  - Max Size: 10MB (configurable via `SKILLOS_ATTACHMENT_MAX_SIZE_BYTES`)
  - Allowed Types: `application/json`, `application/pdf`, `text/plain`, `text/csv`, `image/*`

### Strict JWT Verification

In production environments (`SKILLOS_ENV=prod`), we now forcibly disable `allow_unverified` tokens, ignoring configuration that might relax security.

- **File**: `skillos/jwt_auth.py`
- **Logic**: If `SKILLOS_ENV` is `prod` `dev` flags are overridden to ensure `verify=True`.

### Rate Limiting

A generic rate limiting module was added and integrated into Webhooks.

- **File**: `skillos/rate_limit.py`
- **Integration**: `skillos/webhooks.py`
- **Key**: Tenant-scoped keys `tenant:{tenant_id}:webhook:{trigger_id}` to prevent cross-tenant noisy neighbor issues.
- **Fallback**: Works in-memory even if global cache is disabled.

## 2. Reliability Engineering

### Dead Letter Queue (DLQ) Recovery

Added a mechanism to recover "failed" jobs back to "queued" state for manual or automated recovery.

- **File**: `skillos/jobs.py`
- **Method**: `JobStore.requeue_dead_letters(max_retries_bump=1)`
- **Behavior**: Resets status to `queued` and increments `max_retries` so the job allows one more attempt.

### Budget Logic Audit

Confirmed that budget deduction happens *after* all security checks (Permissions, Approvals, Circuit Breakers), ensuring users are not charged for blocked requests.

- **Pipeline Order**: Permissions -> Approvals -> Circuit -> Budget.

## 3. Operational Readiness

### Health Checks

New module `skillos/health.py` provides checks for:

- Disk Space (<100MB warning)
- Database (SQL generic check)
- Redis Cache (Read/Write check)
- **Endpoint**: `/health` now returns HTTP 503 if system is unhealthy.

### Centralized Config

New module `skillos/config.py` centralizes environment validation for critical settings (Postgres DSN, Redis URL, Log Level).

## 4. Real-World Behavior (Fixtures)

### Fixture Alignment

We updated `tests/conftest.py` to auto-generate dummy implementation files for skills defined in `golden_skill_catalog.json`.

- **Problem**: Tests defined metadata for skills but no Python code, causing runtime `ImportError` when `SkillRegistry` tried to load them.
- **Fix**: `write_skill_catalog` fixture now generates a minimal `.py` file with a `run()` function for every entrypoint defined in the catalog.

## Verification

- **Security Tests**: `pytest tests/unit/test_security_hardening.py` (Passed)
- **DLQ Tests**: `pytest tests/unit/test_jobs_dlq.py` (Passed)
- **Critical Fixes**:
  - Fixed syntax error in `webhooks.py`.
  - Fixed SQLite lock issue in `jobs.py`.
  - Fixed `pytest.ANY` attribute error.
