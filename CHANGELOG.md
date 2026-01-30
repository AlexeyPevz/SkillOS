# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [Unreleased]
### Added
- Placeholder for upcoming changes.

## [0.2.1] - 2026-01-30
### Added
- PyPI publish workflow triggered on version tags.
- GitHub Release workflow with release notes lookup.

## [0.2.0] - 2026-01-30
### Added
- Session manager with SQLite storage, API endpoints, and session-aware orchestration.
- Execution kernels (local) with execution_mode support and session context propagation.
- Eval-as-code framework in YAML with matchers, limits, timeouts, and result persistence.
- CLI command `eval-skill` and eval gating hooks for skill scaffolding.
- API endpoint for running evals with optional result saving.
- Session-focused tests and eval tests in CI.

### Changed
- Orchestrator and pipeline now pass `session_context` to skills.
- Skill registry execution paths route through kernels consistently.
- Documentation updated for SkillOS v2 proposal and walkthrough changes.

### Fixed
- Composition fallback executes via kernels instead of missing entrypoint helpers.
- Session history saved across multi-mode execution paths.
### Added
- Zero-YAML SDK decorator (@skill) with auto-discovery from implementations/.
- SkillFlow for cyclic/stateful skill execution.
- Dev-mode convenience runner Orchestrator.run_simple.
- Integration tests for relative imports and dev-mode execution.

### Changed
- Skill registry loads modules via importlib and initializes package parents for reliable relative imports.
- Walkthrough updated with Zero-YAML, dev-mode, and import stability details.

### Fixed
- Dev-mode logging no longer crashes on mock serialization.
- Module cache cleanup on failed skill loads to prevent poisoning.

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
