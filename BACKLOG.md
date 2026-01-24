# SkillOS MVP Backlog

**Version:** 1.0  
**Sprint:** MVP (Weeks 0-4)  
**Last Updated:** January 13, 2026

---

## 📊 Backlog Overview

**Total Tasks:** 78  
**P0 (Critical):** 22  
**P1 (MVP Required):** 38  
**P2 (Nice to Have):** 18

**Estimated Effort:** 120-140 hours (4 weeks full-time)

---

## 🎯 Priority Levels

- **P0** — Blockers, must have for basic functionality
- **P1** — Required for MVP acceptance criteria
- **P2** — Nice to have, can defer to v1.0

---

## 📦 Epic 1: Foundation (Week 1)

**Goal:** Core infrastructure working  
**Estimated:** 32 hours

### Project Setup

#### TASK-001 [P0] Initialize Python Project
**Estimated:** 2h  
**Description:** Setup poetry project with dependencies

**Acceptance Criteria:**
- [ ] `pyproject.toml` with all dependencies
- [ ] Python 3.11+ configured
- [ ] Virtual environment working
- [ ] Can import main modules

**Dependencies (pyproject.toml):**
- python = "^3.11"
- pydantic = "^2.5"
- click = "^8.1"
- asyncpg = "^0.29"
- redis = "^5.0"
- pyyaml = "^6.0"
- python-dotenv = "^1.0"
- httpx = "^0.25"
- structlog = "^24.1"

**Subtasks:**
- [ ] Create `pyproject.toml`
- [ ] Setup `.env.example`
- [ ] Create basic folder structure
- [ ] Initialize git repo

---

#### TASK-002 [P0] Setup Docker Environment
**Estimated:** 2h  
**Description:** Docker Compose for Postgres + Redis

**Acceptance Criteria:**
- [ ] `docker-compose.yml` working
- [ ] Postgres 15 accessible
- [ ] Redis 7 accessible
- [ ] Persistent volumes configured

**Subtasks:**
- [ ] Create `docker-compose.yml`
- [ ] Test DB connections
- [ ] Setup init scripts for DB schema

---

#### TASK-003 [P0] Database Schema
**Estimated:** 3h  
**Description:** Create Postgres tables for MVP

**Tables needed:**
- skills (metadata cache)
- execution_logs (request history)
- budget_usage (tracking)

**Subtasks:**
- [ ] Write migration SQL
- [ ] Create migration runner
- [ ] Test schema creation

---

### Core Models

#### TASK-004 [P0] Pydantic Models
**Estimated:** 4h  
**Description:** Define all data models

**Files to create:**
- `skillos/skills/models.py`

**Models to implement:**
- Capabilities
- RiskFactors
- CostEstimate
- ToolConfig
- SkillMetadata
- UserContext
- ExecutionContext
- Result
- ExecutionPlan

**Subtasks:**
- [ ] Define all models
- [ ] Add validation rules
- [ ] Write unit tests for models

---

### Orchestrator Brain

#### TASK-005 [P0] Complexity Scorer
**Estimated:** 4h  
**Description:** Implement basic complexity scoring

**File:** `skillos/kernel/complexity_scorer.py`

**Features:**
- Action verb counting
- Conjunction detection
- Conditional detection
- Length-based scoring (capped)

**Algorithm:**
- Extract verbs → +0.5 each
- Conjunctions (and/then/after) → +0.8 each
- Conditionals (if/when) → +1.0 each
- Length component (capped at 1.5)
- Final score capped at 10.0

**Subtasks:**
- [ ] Implement scorer class
- [ ] Add verb extraction (simple keyword list)
- [ ] Write 10+ test cases
- [ ] Validate on real queries

---

#### TASK-006 [P0] Risk Scorer
**Estimated:** 3h  
**Description:** Calculate risk from skill metadata

**File:** `skillos/kernel/risk_scorer.py`

**Features:**
- Base risk from metadata
- Permission checking
- Capability-based scoring

**Algorithm:**
- Start with base_risk from metadata
- Permission mismatch → return 20 (block)
- External API → +2
- Write capability → +3
- Delete capability → +5
- Final score capped at 20

**Subtasks:**
- [ ] Implement scorer
- [ ] Test with all 15 skills
- [ ] Verify blocking logic

---

#### TASK-007 [P0] Orchestrator Main
**Estimated:** 5h  
**Description:** Main orchestration logic

**File:** `skillos/kernel/orchestrator.py`

**Key methods:**
- `execute(query, user_context)` → Result
- `route_request(query, user_context)` → ExecutionPlan
- `_extract_params(query)` → dict

**Flow:**
1. Route request (find skill)
2. Check budget
3. Calculate risk
4. Execute via tool wrapper

**Subtasks:**
- [ ] Implement orchestrator class
- [ ] Add param extraction (simple dict)
- [ ] Integration tests
- [ ] Error handling

---

### Tool Wrapper

#### TASK-008 [P0] Tool Wrapper Implementation
**Estimated:** 4h  
**Description:** Policy enforcement layer

**File:** `skillos/tools/wrapper.py`

**Features:**
- Permission checking
- Rate limiting
- Error handling
- Logging

**Key methods:**
- `execute(skill, params, user_context)` → Result
- `_check_permissions()` → bool
- `_check_rate_limit()` → bool

**Subtasks:**
- [ ] Implement wrapper class
- [ ] Add permission checks
- [ ] Redis-based rate limiting
- [ ] Unit tests

---

#### TASK-009 [P1] Rate Limiter
**Estimated:** 2h  
**Description:** Redis-based rate limiting

**File:** `skillos/tools/rate_limiter.py`

**Features:**
- Per-skill rate limits
- Per-user rate limits
- Sliding window

**Subtasks:**
- [ ] Implement rate limiter
- [ ] Redis integration
- [ ] Tests

---

### Budget Manager

#### TASK-010 [P0] Budget Manager
**Estimated:** 3h  
**Description:** Track and enforce budgets

**File:** `skillos/kernel/budget_manager.py`

**Features:**
- Token tracking
- Cost tracking
- Hard limits enforcement

**Key methods:**
- `has_budget(tokens)` → bool
- `check_before_call(estimated_tokens, estimated_cost)` → BudgetCheckResult
- `add_usage(tokens, cost)`

**Subtasks:**
- [ ] Implement manager class
- [ ] Add limit checks
- [ ] Persistence to DB
- [ ] Unit tests

---

### Observability

#### TASK-011 [P1] Structured Logging
**Estimated:** 2h  
**Description:** Setup structlog

**File:** `skillos/observability/logger.py`

**Features:**
- JSON output
- ISO timestamps
- Log levels
- Request ID tracking

**Subtasks:**
- [ ] Configure structlog
- [ ] Define event schema
- [ ] Add logging to all components

---

## 📦 Epic 2: Skills (Week 2)

**Goal:** 15 working skills  
**Estimated:** 30 hours

### Zakupki Skills

#### TASK-020 [P1] Skill: search_tenders
**Estimated:** 3h

**Files:**
- `skills/metadata/zakupki/search_tenders.yaml`
- `skills/implementations/zakupki/search_tenders.py`

**Subtasks:**
- [ ] Create YAML metadata
- [ ] Implement Python function
- [ ] Mock zakupki API
- [ ] Write tests (3+ test cases)

---

#### TASK-021 [P1] Skill: analyze_document
**Estimated:** 3h

**Subtasks:**
- [ ] YAML metadata
- [ ] Implementation (LLM-based extraction)
- [ ] Tests

---

#### TASK-022 [P1] Skill: check_requirements
**Estimated:** 2h

**Subtasks:**
- [ ] YAML metadata
- [ ] Implementation
- [ ] Tests

---

### Oysters Skills

#### TASK-023 [P1] Skill: get_pricelist
**Estimated:** 2h

**Subtasks:**
- [ ] YAML metadata
- [ ] Implementation
- [ ] Tests

---

#### TASK-024 [P1] Skill: calculate_logistics
**Estimated:** 2h

---

#### TASK-025 [P1] Skill: calculate_margin
**Estimated:** 2h

---

#### TASK-026 [P1] Skill: generate_quote
**Estimated:** 2h

---

### Travel Skills

#### TASK-027 [P1] Skill: search_flights
**Estimated:** 3h

---

#### TASK-028 [P1] Skill: search_hotels
**Estimated:** 2h

---

#### TASK-029 [P1] Skill: build_itinerary
**Estimated:** 3h

---

### Finance Skills

#### TASK-030 [P1] Skill: get_exchange_rates
**Estimated:** 2h

---

#### TASK-031 [P1] Skill: convert_currency
**Estimated:** 1h

---

#### TASK-032 [P1] Skill: track_expenses
**Estimated:** 2h

---

### Research Skills

#### TASK-033 [P1] Skill: web_search
**Estimated:** 2h

---

#### TASK-034 [P1] Skill: summarize_article
**Estimated:** 2h

---

### Testing Framework

#### TASK-035 [P1] Test Harness for Skills
**Estimated:** 4h

**Description:** Framework to test any skill

**File:** `skillos/testing/skill_tester.py`

**Features:**
- Run test cases against skills
- Generate test reports
- Compare expected vs actual
- Performance metrics

**Subtasks:**
- [ ] Implement tester class
- [ ] Add pytest integration
- [ ] Create fixtures
- [ ] CI pipeline setup

---

## 📦 Epic 3: Integration (Week 3)

**Goal:** All components working together  
**Estimated:** 32 hours

### Skill Registry

#### TASK-040 [P0] YAML Loader
**Estimated:** 3h

**File:** `skillos/skills/loader.py`

**Features:**
- Load YAML files
- Pydantic validation
- Cache in memory

**Subtasks:**
- [ ] Implement loader
- [ ] Add validation
- [ ] Error handling
- [ ] Tests

---

#### TASK-041 [P0] Skill Registry
**Estimated:** 4h

**File:** `skillos/skills/registry.py`

**Key methods:**
- `load_all(path)` — Load all skills from directory
- `search(query, limit=5)` — Simple keyword search
- `get(skill_id)` — Get skill by ID
- `reload()` — Hot-reload all skills

**Subtasks:**
- [ ] Implement registry
- [ ] Add keyword search (simple)
- [ ] Cache management
- [ ] Tests

---

#### TASK-042 [P1] Hot-Reload
**Estimated:** 3h

**Description:** Watch YAML files for changes

**Using:** `watchdog` library

**Subtasks:**
- [ ] Add file watcher
- [ ] Trigger reload on change
- [ ] Graceful error handling
- [ ] Tests

---

### Error Handling

#### TASK-043 [P1] Error Handling Layer
**Estimated:** 4h

**Features:**
- User-friendly error messages
- Error recovery
- Retry logic
- Fallback skills

**Subtasks:**
- [ ] Define error hierarchy
- [ ] Add error handlers
- [ ] Retry logic
- [ ] Tests

---

#### TASK-044 [P2] Fallback Skills
**Estimated:** 2h

**Description:** Use alternative skill if primary fails

**Subtasks:**
- [ ] Define fallback logic
- [ ] Implement in orchestrator
- [ ] Tests

---

### CLI Interface

#### TASK-045 [P0] CLI with Click
**Estimated:** 4h

**File:** `skillos/cli.py`

**Commands:**
- `skillos run "query"` — Execute query
- `skillos add-skill domain/name` — Scaffold new skill
- `skillos test skill_id` — Test specific skill
- `skillos validate-skills` — Validate all YAMLs
- `skillos logs --follow` — Tail logs

**Subtasks:**
- [ ] Implement CLI commands
- [ ] Add help text
- [ ] Error handling
- [ ] Colors/formatting

---

### Storage Clients

#### TASK-046 [P0] Postgres Client
**Estimated:** 3h

**File:** `skillos/storage/postgres.py`

**Features:**
- Connection pooling (asyncpg)
- Query helpers
- Migration support

**Subtasks:**
- [ ] Implement client
- [ ] Add query methods
- [ ] Connection management
- [ ] Tests

---

#### TASK-047 [P0] Redis Client
**Estimated:** 2h

**File:** `skillos/storage/redis.py`

**Features:**
- Connection wrapper
- Rate limiting helpers
- Cache helpers

---

### Configuration

#### TASK-048 [P1] Config Management
**Estimated:** 2h

**File:** `skillos/config.py`

**Features:**
- Load from .env file
- Type validation
- Default values
- Environment overrides

**Key settings:**
- Database URLs
- Budget limits
- LLM API keys
- Log level

---

### Observability

#### TASK-049 [P1] Event Schema Implementation
**Estimated:** 2h

**File:** `skillos/observability/events.py`

**Events:**
- request_received
- skill_selected
- skill_executed
- error_occurred
- budget_check

---

#### TASK-050 [P2] Basic Metrics
**Estimated:** 2h

**Description:** In-memory counters (no Prometheus yet)

**Metrics:**
- Requests total
- Requests by status
- Latency histogram
- Tokens used
- Cost tracking

---

## 📦 Epic 4: Polish (Week 4)

**Goal:** Production-quality for personal use  
**Estimated:** 26 hours

### Bug Fixes & Testing

#### TASK-060 [P1] Integration Testing
**Estimated:** 6h

**Description:** End-to-end tests

**Test scenarios:**
1. Full request flow
2. Budget enforcement
3. Permission blocking
4. Rate limiting
5. Error recovery

---

#### TASK-061 [P1] Edge Case Testing
**Estimated:** 4h

**Scenarios:**
- Empty query
- Very long query (>1000 chars)
- Invalid permissions
- Database down
- Redis down
- LLM API error

---

#### TASK-062 [P1] Performance Testing
**Estimated:** 3h

**Tests:**
- Latency under load
- Memory leaks
- Connection pooling

---

#### TASK-063 [P1] Bug Fixes
**Estimated:** 4h

**Description:** Fix all known bugs from testing

---

### Documentation

#### TASK-064 [P0] README.md
**Estimated:** 2h

**Sections:**
- Quick start
- Installation
- Usage examples
- Architecture overview

---

#### TASK-065 [P1] SKILL_GUIDE.md
**Estimated:** 3h

**Sections:**
- How to add a skill
- YAML schema reference
- Implementation patterns
- Testing guidelines

---

#### TASK-066 [P2] API Reference
**Estimated:** 2h

**Description:** Auto-generated from docstrings

---

### Real Use Case Validation

#### TASK-070 [P0] Validate 5 Use Cases
**Estimated:** 4h

**Test:**
1. Zakupki tender search
2. Oyster margin calculation
3. Travel planning
4. Expense tracking
5. Competitor research

**Record:**
- Accuracy
- Latency
- User experience

---

#### TASK-071 [P1] Demo Video
**Estimated:** 2h

**Content:**
- Quick intro
- Show all 5 use cases
- Add skill demo
- Architecture walkthrough (3 min)

---

## 📊 Backlog Summary by Week

### Week 1: Foundation
| Priority | Tasks | Estimated Hours |
|----------|-------|-----------------|
| P0 | 8 | 26h |
| P1 | 2 | 4h |
| P2 | 1 | 2h |
| **Total** | **11** | **32h** |

### Week 2: Skills
| Priority | Tasks | Estimated Hours |
|----------|-------|-----------------|
| P0 | 0 | 0h |
| P1 | 16 | 30h |
| P2 | 0 | 0h |
| **Total** | **16** | **30h** |

### Week 3: Integration
| Priority | Tasks | Estimated Hours |
|----------|-------|-----------------|
| P0 | 5 | 16h |
| P1 | 5 | 13h |
| P2 | 2 | 4h |
| **Total** | **12** | **33h** |

### Week 4: Polish
| Priority | Tasks | Estimated Hours |
|----------|-------|-----------------|
| P0 | 2 | 6h |
| P1 | 6 | 18h |
| P2 | 1 | 2h |
| **Total** | **9** | **26h** |

---

## 🎯 Critical Path

**Must complete in order:**

1. TASK-001 → TASK-002 → TASK-003 (Setup)
2. TASK-004 (Models)
3. TASK-005 → TASK-006 → TASK-007 (Orchestrator)
4. TASK-010 (Budget Manager)
5. TASK-008 (Tool Wrapper)
6. TASK-040 → TASK-041 (Skill Registry)
7. TASK-020 to TASK-034 (Skills - can parallelize)
8. TASK-045 (CLI)
9. TASK-060 to TASK-063 (Testing)
10. TASK-070 (Validation)

---

## 📈 Progress Tracking

### Definition of Done (per task)

- [ ] Code implemented
- [ ] Unit tests written (>80% coverage)
- [ ] Integration tests (if applicable)
- [ ] Documentation updated
- [ ] Code review passed (self-review for solo)
- [ ] Merged to main

### Weekly Goals

**Week 1 Goal:** All P0 tasks complete + working orchestrator  
**Week 2 Goal:** 15 skills implemented and tested  
**Week 3 Goal:** Full integration working  
**Week 4 Goal:** All acceptance criteria met

---

## 🚀 Getting Started

**First 5 tasks to do TODAY:**

1. **TASK-001** — Initialize project (2h)
2. **TASK-002** — Setup Docker (2h)
3. **TASK-003** — Database schema (3h)
4. **TASK-004** — Pydantic models (4h)
5. **TASK-005** — Complexity scorer (4h)

**Total:** 15h (2 full days)

After these, you'll have:
- ✅ Working development environment
- ✅ Data models defined
- ✅ First component (scorer) working

---

**Next:** See [MVP_SPEC.md](./MVP_SPEC.md) for detailed specifications or [ROADMAP.md](./ROADMAP.md) for long-term vision.
