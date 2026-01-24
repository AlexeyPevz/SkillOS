# SkillOS MVP Specification

**Version:** 1.0  
**Timeline:** Weeks 0-4 (January 13 - February 10, 2026)  
**Status:** Ready to Start  
**Owner:** Solo developer

---

## 🎯 MVP Goal

**Prove the core hypothesis:**
> "Declarative skill definition + smart orchestration = fast, reliable business automation"

**Success looks like:**
- Add new skill in 10 minutes
- System chooses correct skill 80%+ of the time
- Budget enforcement prevents cost overruns
- Solves 5 real personal tasks end-to-end

**If successful:** Green light for v1.0 (production-ready)

---

## 📦 What's In Scope

### Core Architecture

```
┌─────────────────────────────────────────────────────┐
│                   CLI Interface                      │
└───────────────────┬─────────────────────────────────┘
                    │
┌───────────────────▼─────────────────────────────────┐
│              Orchestrator Brain                      │
│  • Complexity Scorer                                 │
│  • Risk Scorer                                       │
│  • Mode Selector (Single only)                      │
└───────────────────┬─────────────────────────────────┘
                    │
         ┌──────────┼──────────┐
         │          │          │
┌────────▼────┐ ┌──▼──────┐ ┌─▼──────────┐
│   Skill     │ │ Budget  │ │   Tool     │
│  Registry   │ │ Manager │ │  Wrapper   │
└────────┬────┘ └─────────┘ └─────┬──────┘
         │                         │
┌────────▼─────────────────────────▼──────┐
│         Postgres + Redis                 │
└──────────────────────────────────────────┘
```

### Interfaces
- CLI (Click) for local workflows
- FastAPI for HTTP integration (run/validate/skills/schedules)

### Components to Build

#### 1. Skill Registry
**Purpose:** Store and load skills declaratively

**Features:**
- YAML-based skill metadata
- Pydantic validation
- Hot-reload without restart
- Simple keyword-based search (no semantic yet)

**File Structure:**
```
skills/
├── metadata/
│   ├── zakupki/
│   │   ├── search_tenders.yaml
│   │   ├── analyze_document.yaml
│   │   └── check_requirements.yaml
│   ├── oysters/
│   │   ├── get_pricelist.yaml
│   │   ├── calculate_logistics.yaml
│   │   └── ...
│   └── travel/
│       ├── search_flights.yaml
│       └── ...
└── implementations/
    ├── zakupki/
    │   ├── search_tenders.py
    │   └── ...
    ├── oysters/
    └── travel/
```

#### 2. Orchestrator Brain
**Purpose:** Decide which skill to use

**Components:**
- `ComplexityScorer` — estimate query complexity (0-10)
- `RiskScorer` — estimate operation risk (0-20)
- `ModeSelector` — choose execution mode (Single only for MVP)

**Decision Logic (Simplified):**
```python
def route_request(query: str, context: dict) -> ExecutionPlan:
    complexity = complexity_scorer.score(query)

    # Find matching skills (keyword search)
    candidates = skill_registry.search(query, limit=5)

    if not candidates:
        return ExecutionPlan(status="no_skill_found")

    # Pick best match (simple scoring)
    best_skill = max(candidates, key=lambda s: s.match_score)

    # Calculate risk
    risk = risk_scorer.calculate(best_skill, context)

    # Check budget
    if not budget_manager.has_budget(best_skill.estimated_cost):
        return ExecutionPlan(status="budget_exceeded")

    return ExecutionPlan(
        mode="single",
        skill=best_skill,
        estimated_risk=risk
    )
```

#### 3. Tool Wrapper
**Purpose:** Enforce policies at execution time

**Features:**
- Permission checking
- Rate limiting (Redis-based)
- Error handling
- Basic logging

**Interface:**
```python
class ToolWrapper:
    def execute(
        self,
        skill: Skill,
        params: dict,
        user_context: UserContext
    ) -> Result:
        # 1. Check permissions
        self._check_permissions(skill, user_context)

        # 2. Check rate limits
        self._check_rate_limit(skill, user_context)

        # 3. Execute
        try:
            output = skill.run(params)
            return Result(status="success", output=output)
        except Exception as e:
            return Result(status="error", error=str(e))
```

#### 4. Budget Manager
**Purpose:** Track and enforce token/cost limits

**Features:**
- Per-request token tracking
- Cost estimation before execution
- Hard limits (stops at threshold)
- Simple in-memory storage for MVP

**Limits:**
```python
BUDGET_LIMITS = {
    "max_tokens_per_request": 50_000,
    "max_cost_per_request_usd": 0.50,
    "max_seconds_per_request": 300
}
```

#### 5. Observability (Basic)
**Purpose:** Understand what's happening

**Features:**
- Structured JSON logging
- Event schema (request, skill_execution, error)
- Basic stdout logging (no Prometheus yet)

**Event Types:**
```python
{
    "request_received": {
        "request_id": "req_123",
        "query": "найти тендеры по ремонту дорог",
        "timestamp": 1705152000
    },
    "skill_selected": {
        "request_id": "req_123",
        "skill_id": "zakupki.search_tenders",
        "match_score": 0.85
    },
    "skill_executed": {
        "request_id": "req_123",
        "status": "success",
        "latency_ms": 1234,
        "tokens_used": 1500,
        "cost_usd": 0.003
    }
}
```

---

## 🚫 What's OUT of Scope

**Explicitly NOT building in MVP:**

- ❌ Parallel/Pipeline modes (only Single)
- ❌ Semantic search (Qdrant)
- ❌ Skill Graph (networkx/Neo4j)
- ❌ HITL Gate (approval flow)
- ❌ Multi-tenancy
- ❌ Full Web API surface (beyond the minimal FastAPI endpoints)
- ❌ Circuit Breaker
- ❌ Idempotency
- ❌ Advanced caching
- ❌ Web UI
- ❌ Authentication
- ❌ Deployment automation

**Why?** Focus on core value: "declarative skills work reliably"

---

## 📋 Skill Library (15 Skills)

### Zakupki (3 skills)

#### 1. search_tenders
```yaml
skill_id: "zakupki.search_tenders"
name: "Search Government Tenders"
description: "Search zakupki.gov.ru for tenders matching criteria"
domain: "zakupki"
capabilities:
  read: true
  write: false
  external_api: true
permissions_required:
  - "zakupki:read"
risk_factors:
  base_risk: 2
cost_estimate:
  tokens: 2000
  usd: 0.004
tools:
  - name: "zakupki_api"
    config:
      rate_limit: 10/minute
```

**Implementation:**
```python
def execute(params: dict, context: ExecutionContext) -> dict:
    keywords = params.get("keywords", [])
    region = params.get("region")
    budget_min = params.get("budget_min")

    results = context.tools.zakupki_api.search(
        keywords=keywords,
        region=region,
        budget_range=(budget_min, None)
    )

    return {
        "tenders": results[:10],
        "count": len(results)
    }
```

#### 2. analyze_document
```yaml
skill_id: "zakupki.analyze_document"
name: "Analyze Tender Document"
description: "Extract key information from tender documentation"
domain: "zakupki"
capabilities:
  read: true
  analyze: true
permissions_required:
  - "zakupki:read"
risk_factors:
  base_risk: 3
cost_estimate:
  tokens: 5000
  usd: 0.010
```

#### 3. check_requirements
```yaml
skill_id: "zakupki.check_requirements"
name: "Check Tender Requirements"
description: "Verify if company meets tender requirements"
domain: "zakupki"
capabilities:
  read: true
  analyze: true
permissions_required:
  - "zakupki:read"
risk_factors:
  base_risk: 2
```

### Oysters (4 skills)

#### 4. get_pricelist
```yaml
skill_id: "oysters.get_pricelist"
name: "Get Current Oyster Prices"
description: "Fetch latest wholesale oyster prices"
domain: "oysters"
capabilities:
  read: true
  external_api: true
permissions_required:
  - "oysters:read"
risk_factors:
  base_risk: 1
cost_estimate:
  tokens: 500
  usd: 0.001
```

#### 5. calculate_logistics
```yaml
skill_id: "oysters.calculate_logistics"
name: "Calculate Delivery Cost"
description: "Estimate logistics cost for oyster delivery"
domain: "oysters"
capabilities:
  read: true
  compute: true
permissions_required:
  - "oysters:read"
risk_factors:
  base_risk: 1
```

#### 6. calculate_margin
```yaml
skill_id: "oysters.calculate_margin"
name: "Calculate Profit Margin"
description: "Compute profit margin on oyster sales"
domain: "oysters"
```

#### 7. generate_quote
```yaml
skill_id: "oysters.generate_quote"
name: "Generate Customer Quote"
description: "Create price quote for customer"
domain: "oysters"
```

### Travel (3 skills)

#### 8. search_flights
```yaml
skill_id: "travel.search_flights"
name: "Search Flights"
description: "Find flights by route and dates"
domain: "travel"
capabilities:
  read: true
  external_api: true
permissions_required:
  - "travel:read"
risk_factors:
  base_risk: 2
cost_estimate:
  tokens: 1500
  usd: 0.003
tools:
  - name: "aviasales_api"
```

#### 9. search_hotels
```yaml
skill_id: "travel.search_hotels"
name: "Search Hotels"
description: "Find hotels by location and dates"
domain: "travel"
```

#### 10. build_itinerary
```yaml
skill_id: "travel.build_itinerary"
name: "Build Travel Itinerary"
description: "Create day-by-day travel plan"
domain: "travel"
```

### Finance (3 skills)

#### 11. get_exchange_rates
```yaml
skill_id: "finance.get_exchange_rates"
name: "Get Currency Rates"
description: "Fetch current exchange rates"
domain: "finance"
```

#### 12. convert_currency
```yaml
skill_id: "finance.convert_currency"
name: "Convert Currency"
description: "Convert amount between currencies"
domain: "finance"
```

#### 13. track_expenses
```yaml
skill_id: "finance.track_expenses"
name: "Track Expenses"
description: "Log and categorize expenses"
domain: "finance"
```

### Research (2 skills)

#### 14. web_search
```yaml
skill_id: "research.web_search"
name: "Search Web"
description: "Search internet for information"
domain: "research"
```

#### 15. summarize_article
```yaml
skill_id: "research.summarize_article"
name: "Summarize Article"
description: "Extract key points from article"
domain: "research"
```

---

## 🗂️ Data Models

### SkillMetadata (Pydantic)

```python
from pydantic import BaseModel
from typing import List, Dict, Optional

class Capabilities(BaseModel):
    read: bool = False
    write: bool = False
    delete: bool = False
    analyze: bool = False
    compute: bool = False
    external_api: bool = False

class RiskFactors(BaseModel):
    base_risk: int  # 0-20
    data_sensitivity: int = 0

class CostEstimate(BaseModel):
    tokens: int
    usd: float

class ToolConfig(BaseModel):
    name: str
    config: Dict = {}

class SkillMetadata(BaseModel):
    skill_id: str
    version: str = "1.0.0"
    name: str
    description: str
    domain: str
    capabilities: Capabilities
    permissions_required: List[str]
    risk_factors: RiskFactors
    cost_estimate: CostEstimate
    tools: List[ToolConfig] = []

    # Computed
    match_score: float = 0.0  # Set during search
```

### ExecutionContext

```python
class UserContext(BaseModel):
    user_id: str
    permissions: List[str]
    budget_remaining: float

class ExecutionContext(BaseModel):
    request_id: str
    user: UserContext
    tools: ToolRegistry
    logger: Logger
```

### Result

```python
class Result(BaseModel):
    status: str  # "success" | "error" | "budget_exceeded"
    output: Optional[Dict] = None
    error: Optional[str] = None
    metadata: Dict = {}  # tokens_used, cost_usd, latency_ms
```

---

## 🔧 Technology Stack

### Core
- **Python 3.11+**
- **Pydantic v2** — data validation
- **Click** — CLI framework
- **asyncio** — async I/O

### Storage
- **PostgreSQL 15** — skill metadata, execution logs
- **Redis 7** — rate limiting, simple caching

### LLM
- **Google Gemini 2.0 Flash** — primary model
- **Anthropic Claude 3.5 Sonnet** — fallback

### Development
- **pytest** — testing
- **ruff** — linting
- **black** — formatting
- **pyproject.toml** — dependency management

### Infrastructure
- **Docker Compose** — local development
- **dotenv** — configuration

---

## 📁 Project Structure

```
skillos/
├── pyproject.toml
├── README.md
├── .env.example
├── docker-compose.yml
│
├── skillos/
│   ├── __init__.py
│   ├── cli.py                    # Click CLI interface
│   ├── config.py                 # Configuration
│   │
│   ├── kernel/
│   │   ├── __init__.py
│   │   ├── orchestrator.py       # Main orchestrator
│   │   ├── complexity_scorer.py
│   │   ├── risk_scorer.py
│   │   └── budget_manager.py
│   │
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── registry.py           # Skill registry
│   │   ├── loader.py             # YAML loader
│   │   ├── models.py             # Pydantic models
│   │   │
│   │   ├── metadata/             # YAML configs
│   │   │   ├── zakupki/
│   │   │   ├── oysters/
│   │   │   ├── travel/
│   │   │   ├── finance/
│   │   │   └── research/
│   │   │
│   │   └── implementations/      # Python code
│   │       ├── zakupki/
│   │       ├── oysters/
│   │       ├── travel/
│   │       ├── finance/
│   │       └── research/
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── wrapper.py            # Tool wrapper
│   │   └── registry.py           # Tool registry
│   │
│   ├── observability/
│   │   ├── __init__.py
│   │   ├── logger.py             # Structured logging
│   │   └── events.py             # Event definitions
│   │
│   └── storage/
│       ├── __init__.py
│       ├── postgres.py           # Postgres client
│       └── redis.py              # Redis client
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
└── docs/
    ├── ROADMAP.md
    ├── MVP_SPEC.md               # This file
    └── SKILL_GUIDE.md            # How to add skills
```

---

## ⏱️ Week-by-Week Plan

### Week 1: Foundation (Days 1-7)

**Goal:** Core infrastructure working

#### Day 1-2: Project Setup
- [ ] Initialize Python project (pyproject.toml)
- [ ] Setup Postgres + Redis (Docker Compose)
- [ ] Create base project structure
- [ ] Configure development environment

**Deliverable:** `docker-compose up` works, can connect to DBs

#### Day 3-4: Orchestrator Brain
- [ ] Implement ComplexityScorer (basic heuristics)
- [ ] Implement RiskScorer (metadata-based)
- [ ] Implement simple ModeSelector (always Single)
- [ ] Unit tests for scorers

**Deliverable:** `orchestrator.route_request()` returns ExecutionPlan

#### Day 5-7: Tool Wrapper + Budget Manager
- [ ] Implement ToolWrapper with permission checks
- [ ] Implement BudgetManager (in-memory)
- [ ] Rate limiting with Redis
- [ ] Integration tests

**Deliverable:** Can execute a mock skill with all policies enforced

---

### Week 2: Skills (Days 8-14)

**Goal:** First 10 working skills

#### Day 8-10: Zakupki Skills
- [ ] Create YAML metadata for 3 zakupki skills
- [ ] Implement search_tenders (mock API for now)
- [ ] Implement analyze_document
- [ ] Implement check_requirements
- [ ] Write tests

**Deliverable:** `skillos run "найти тендеры по ремонту"` works

#### Day 11-12: Oysters Skills
- [ ] Create 4 oysters skills
- [ ] Implement with mock data
- [ ] Write tests

**Deliverable:** Can calculate profit margin for oyster order

#### Day 13-14: Testing Framework
- [ ] Create test harness for skills
- [ ] Add test cases for each skill
- [ ] Setup pytest fixtures
- [ ] CI pipeline (GitHub Actions)

**Deliverable:** `pytest` runs all tests, >80% coverage

---

### Week 3: Integration (Days 15-21)

**Goal:** All components work together

#### Day 15-17: Skill Registry
- [ ] Implement YAML loader with Pydantic validation
- [ ] Implement hot-reload (watch files)
- [ ] Implement keyword search
- [ ] Cache loaded skills in memory

**Deliverable:** Add new skill, see it instantly without restart

#### Day 18-19: Error Handling
- [ ] Graceful error handling in orchestrator
- [ ] User-friendly error messages
- [ ] Retry logic for transient failures
- [ ] Fallback to alternative skills

**Deliverable:** System doesn't crash on bad input

#### Day 20-21: Observability
- [ ] Structured JSON logging
- [ ] Event schema implementation
- [ ] Request tracing (request_id throughout)
- [ ] Basic metrics (counts, latencies)

**Deliverable:** Can debug any request from logs

---

### Week 4: Polish (Days 22-28)

**Goal:** Production-quality for personal use

#### Day 22-23: Bug Fixes
- [ ] Fix all known bugs
- [ ] Handle edge cases
- [ ] Performance optimization
- [ ] Memory leak checks

**Deliverable:** Stable for daily use

#### Day 24-25: Documentation
- [ ] README with quick start
- [ ] SKILL_GUIDE.md (how to add skills)
- [ ] API reference (function signatures)
- [ ] Example queries

**Deliverable:** Someone else can add a skill using docs

#### Day 26-28: Real Use Case Validation
- [ ] Test all 5 personal use cases:
  1. Find zakupki tender
  2. Calculate oyster margin
  3. Plan weekend trip
  4. Track monthly expenses
  5. Research competitor
- [ ] Measure accuracy
- [ ] Collect feedback (from yourself!)
- [ ] Record demo video

**Deliverable:** MVP complete, ready to decide GO/NO-GO

---

## ✅ Acceptance Criteria

### Hard Requirements (Must Pass)

1. **Skill Addition Speed**
   - [ ] Can add new skill in <10 minutes
   - [ ] YAML validation catches errors immediately
   - [ ] Hot-reload works without restart

2. **Routing Accuracy**
   - [ ] Selects correct skill 80%+ of the time
   - [ ] Test on 50 diverse queries
   - [ ] Manual verification of results

3. **Budget Enforcement**
   - [ ] Stops at configured token limit
   - [ ] Stops at configured cost limit
   - [ ] Never exceeds by >10%

4. **Security**
   - [ ] No permission bypasses
   - [ ] Rate limits enforced
   - [ ] Test with unauthorized user context

5. **Real Tasks**
   - [ ] Solve zakupki tender search
   - [ ] Solve oyster margin calculation
   - [ ] Solve travel planning
   - [ ] Solve expense tracking
   - [ ] Solve competitor research

### Performance Targets

- **Request latency:** <2s p95
- **Skill selection:** <100ms
- **Memory usage:** <512MB
- **Crash rate:** 0% on valid inputs

### Developer Experience

- **Setup time:** <30 minutes
- **Skill addition:** <10 minutes
- **Test run:** <5 seconds
- **Documentation:** Complete enough for someone else to contribute

---

## 🧪 Testing Strategy

### Unit Tests (70% coverage target)

```python
# tests/unit/test_orchestrator.py
def test_complexity_scorer_simple_query():
    scorer = ComplexityScorer()
    score = scorer.score("найти тендеры")
    assert 0 <= score <= 3  # Simple query

def test_complexity_scorer_complex_query():
    scorer = ComplexityScorer()
    score = scorer.score(
        "найти тендеры по ремонту дорог, "
        "проанализировать документацию и "
        "проверить соответствие требованиям"
    )
    assert 6 <= score <= 10  # Complex multi-step

def test_budget_manager_enforces_limit():
    manager = BudgetManager(max_tokens=1000)
    manager.add_usage(tokens=900)

    check = manager.check_before_call(estimated_tokens=200)
    assert check.allowed == False
```

### Integration Tests

```python
# tests/integration/test_end_to_end.py
def test_full_request_flow(db, redis):
    orchestrator = Orchestrator(db=db, redis=redis)

    result = orchestrator.execute(
        query="найти тендеры по ремонту дорог в Москве",
        user_context=UserContext(
            user_id="test_user",
            permissions=["zakupki:read"]
        )
    )

    assert result.status == "success"
    assert "tenders" in result.output
    assert len(result.output["tenders"]) > 0
```

### Manual Test Cases

**Test Suite: MVP Validation**

1. **Zakupki Search**
   - Query: "найти тендеры на ремонт школ бюджетом больше 5 млн"
   - Expected: List of relevant tenders
   - Pass criteria: ≥5 relevant results

2. **Oyster Margin**
   - Query: "рассчитать маржу на устрицы если закупка 500р, доставка 100р, продажа 1200р"
   - Expected: Profit margin calculation
   - Pass criteria: Correct math (1200 - 600 = 600 / 1200 = 50%)

3. **Flight Search**
   - Query: "найти рейсы Москва-Сочи на 15 февраля"
   - Expected: List of flights
   - Pass criteria: ≥3 flight options

4. **Currency Conversion**
   - Query: "конвертировать 1000 USD в рубли"
   - Expected: Current exchange rate calculation
   - Pass criteria: Within 1% of real rate

5. **Budget Limit**
   - Query: [50 sequential requests]
   - Expected: Stops at token limit
   - Pass criteria: System blocks before exceeding limit

---

## 🎯 Success Metrics

### Quantitative

| Metric | Target | Measurement |
|--------|--------|-------------|
| Skill Addition Time | <10 min | Manual timing |
| Routing Accuracy | >80% | 50 test queries |
| Budget Compliance | 100% | Automated tests |
| Crash Rate | 0% | Error logs |
| Test Coverage | >70% | pytest-cov |
| Request Latency p95 | <2s | Logs analysis |

### Qualitative

- [ ] "I want to use this every day" (personal dogfooding)
- [ ] "Adding skills is easy" (subjective assessment)
- [ ] "Errors are clear and actionable"
- [ ] "Documentation is sufficient"

---

## 🚦 Go/No-Go Decision Criteria

**After Week 4, evaluate:**

### GO to v1.0 if:
- ✅ All 5 hard requirements passed
- ✅ All 5 manual test cases work
- ✅ Personal assessment: "I want to use this daily"
- ✅ Clear path to adding 35 more skills (Week 2 proved it's easy)
- ✅ No major architectural problems discovered

### NO-GO (iterate MVP) if:
- ❌ Skill addition takes >30 minutes
- ❌ Routing accuracy <70%
- ❌ Constant crashes/instability
- ❌ Architecture feels fundamentally wrong

### PIVOT if:
- ❌ Core hypothesis is wrong (declarative approach doesn't work)
- ❌ Even personal use cases are too hard to solve
- ❌ Complexity exploded beyond control

---

## 📚 Reference Materials

### Key Documents
- [ROADMAP.md](./ROADMAP.md) — Full 12-month plan
- [ARCHITECTURE_V4.md](./ARCHITECTURE_V4.md) — Complete v4.0 architecture (North Star)

### External Resources
- Pydantic docs: https://docs.pydantic.dev
- Gemini API: https://ai.google.dev/docs
- Click CLI: https://click.palletsprojects.com

---

## 🛠️ Development Commands

```bash
# Setup
git clone <repo>
cd skillos
poetry install
docker-compose up -d

# Run
poetry run skillos run "найти тендеры"

# Test
poetry run pytest

# Add skill
poetry run skillos add-skill travel/search_trains

# Validate all skills
poetry run skillos validate-skills

# Watch logs
poetry run skillos logs --follow
```

---

**Ready to start?** Begin with Week 1, Day 1: Project Setup.

**Questions?** Review [ROADMAP.md](./ROADMAP.md) for context or [ARCHITECTURE_V4.md](./ARCHITECTURE_V4.md) for technical deep-dive.
