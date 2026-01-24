# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]

## [0.1.0] - 2026-01-24
### Added
- Health checks wired into the API health endpoint with 503 on unhealthy.
- Attachment validation limits for size and content types.
- Dead-letter requeue for jobs.
- Centralized config helper and system health helper.
- Strict (Redis) rate limiter option for multi-instance deployments.

### Changed
- Webhook signatures are required by default (opt-out via env flag).
- Budget checks only charge after allow/approval/circuit validation.
- Policies reload automatically when approval policy changes.

### Security
- JWT verification hardened for production settings.
- Tenant-scoped rate limiting for webhooks.

### Fixed
- Circuit breaker persistence is now safe under parallel execution.
- Test fixtures generate dummy implementations for skill entrypoints.
