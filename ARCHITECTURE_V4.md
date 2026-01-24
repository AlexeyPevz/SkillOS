# SkillOS v4.0 Architecture Specification

**Version:** 4.0  
**Last Updated:** January 13, 2026  
**Status:** North Star Architecture  
**Document Owner:** Technical Lead

---

## 📋 Document Overview

This document describes the complete technical architecture for SkillOS v4.0 — the self-extending adaptive multi-agent operating system.

**Target Audience:** Engineers, architects, technical stakeholders

**Related Documents:**
- [PRD.md](./PRD.md) — Product requirements
- [ROADMAP.md](./ROADMAP.md) — Phased development plan
- [MVP_SPEC.md](./MVP_SPEC.md) — MVP implementation details

---

## 🎯 Architecture Principles

### 1. Declarative Over Imperative
Skills are defined in YAML, not code. Code is the implementation detail.

### 2. Defense-in-Depth
Security at every layer: authentication, authorization, execution, monitoring.

### 3. Budget-Aware
Every operation has cost tracking and limits.

### 4. Fail-Safe
System degrades gracefully, never catastrophically.

### 5. Observable
Every decision and action is logged and traceable.

### 6. Self-Improving
System learns from usage and optimizes itself.

---

## 🏗️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client Layer                              │
│  CLI  │  Web UI  │  API  │  Telegram Bot  │  Webhooks          │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                   API Gateway (FastAPI)                          │
│  • Authentication (JWT)                                          │
│  • Rate Limiting                                                 │
│  • Request Validation                                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  Orchestrator Brain                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Complexity  │  │     Risk     │  │    Mode      │          │
│  │   Scorer     │  │   Scorer     │  │  Selector    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                   │
│  ┌────────────────────────────────────────────────┐             │
│  │         Execution Planner                      │             │
│  │  • Single    • Parallel    • Pipeline          │             │
│  └────────────────────────────────────────────────┘             │
└────────────────────────┬────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
┌─────────▼────┐  ┌──────▼──────┐  ┌───▼────────┐
│    Skill     │  │   Budget    │  │   Policy   │
│   Registry   │  │   Manager   │  │   Engine   │
└─────────┬────┘  └─────────────┘  └────────────┘
          │
          │        ┌──────────────────┐
          └────────►  Skill Graph     │ (v2.0+)
                   │  (Neo4j)         │
                   └──────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                    Execution Layer                                │
│                                                                    │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐     │
│  │  Tool Wrapper  │  │  HITL Gate     │  │ Circuit        │     │
│  │                │  │  (Approval)    │  │ Breaker        │     │
│  └────────────────┘  └────────────────┘  └────────────────┘     │
│                                                                    │
│  ┌────────────────────────────────────────────────────────┐      │
│  │           Skill Implementations (Python)               │      │
│  │  • zakupki/*  • oysters/*  • travel/*  • finance/*     │      │
│  └────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                       Storage Layer                               │
│                                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Postgres │  │  Redis   │  │  Qdrant  │  │  Neo4j   │        │
│  │ (meta)   │  │ (cache)  │  │(vectors) │  │ (graph)  │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                   Observability Layer                             │
│                                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Structlog│  │ Prometheus│  │  Grafana │  │  Sentry  │        │
│  │ (logs)   │  │ (metrics) │  │  (viz)   │  │ (errors) │        │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

Note: FastAPI handlers are async; blocking orchestration and file IO run in the thread pool.
The CLI remains synchronous.

---

## 🧩 Core Components

### 1. Orchestrator Brain

**Purpose:** Decides which skill(s) to execute and how

**Subcomponents:**

#### 1.1 Complexity Scorer
**File:** `skillos/kernel/complexity_scorer.py`

**Algorithm:**
```python
def score(query: str) -> float:
    # 0-10 scale
    complexity = 0.0

    # Action verbs (0.5 each)
    verbs = extract_verbs(query)
    complexity += len(verbs) * 0.5

    # Conjunctions (multi-step indicator)
    for conj in ["and", "then", "after", "also"]:
        if conj in query.lower():
            complexity += 0.8

    # Conditionals (branching logic)
    for cond in ["if", "when", "unless"]:
        if cond in query.lower():
            complexity += 1.0

    # Length component (capped)
    token_count = len(query.split())
    complexity += min((token_count / 50) * 0.1, 1.5)

    return min(complexity, 10.0)
```

**Thresholds:**
- 0-3: Simple (single skill)
- 4-6: Moderate (might need parallel)
- 7-10: Complex (needs pipeline or decomposition)

---

#### 1.2 Risk Scorer
**File:** `skillos/kernel/risk_scorer.py`

**Algorithm:**
```python
def calculate(skill: SkillMetadata, context: UserContext) -> float:
    # 0-20 scale
    risk = skill.risk_factors.base_risk

    # Permission mismatch = immediate block
    if not has_required_permissions(skill, context):
        return 20  # Block

    # Capability-based risk
    if skill.capabilities.external_api:
        risk += 2
    if skill.capabilities.write:
        risk += 3
    if skill.capabilities.delete:
        risk += 5

    # Data sensitivity
    risk += skill.risk_factors.data_sensitivity

    return min(risk, 20)
```

**Risk Levels:**
- 0-5: Low (auto-execute)
- 6-10: Medium (log + execute)
- 11-15: High (HITL approval required)
- 16-20: Critical (block or require special approval)

---

#### 1.3 Mode Selector
**File:** `skillos/kernel/mode_selector.py`

**Decision Logic:**
```python
def select_mode(
    query: str,
    complexity: float,
    skill_candidates: List[SkillMetadata]
) -> ExecutionMode:

    # Simple query → Single mode
    if complexity < 4 and len(skill_candidates) == 1:
        return ExecutionMode.SINGLE

    # Independent subtasks → Parallel mode
    if can_parallelize(query, skill_candidates):
        return ExecutionMode.PARALLEL

    # Sequential dependency → Pipeline mode
    if has_dependencies(query, skill_candidates):
        return ExecutionMode.PIPELINE

    # Unclear → ask user or default to Single
    return ExecutionMode.SINGLE
```

---

#### 1.4 Execution Planner
**File:** `skillos/kernel/execution_planner.py`

**Responsibilities:**
- Create execution graph
- Resolve dependencies
- Allocate resources
- Generate execution plan

**Output:**
```python
@dataclass
class ExecutionPlan:
    request_id: str
    mode: ExecutionMode  # SINGLE | PARALLEL | PIPELINE
    stages: List[ExecutionStage]
    estimated_cost: float
    estimated_time: float
    risk_level: float
```

---

### 2. Skill Registry

**Purpose:** Store, load, and search skills

**File:** `skillos/skills/registry.py`

**Features:**

#### 2.1 Loading
```python
class SkillRegistry:
    def load_all(self, path: str):
        # Scan directory for YAML files
        # Validate with Pydantic
        # Store in memory + Postgres

    def reload(self):
        # Hot-reload changed files
```

#### 2.2 Search (Hybrid)
```python
def search(
    self,
    query: str,
    limit: int = 5,
    filters: Optional[Dict] = None
) -> List[SkillMetadata]:

    # Phase 1: Keyword match (fast filter)
    keyword_candidates = self._keyword_search(query)

    # Phase 2: Semantic search (Qdrant)
    semantic_candidates = self._semantic_search(query)

    # Phase 3: Graph-based ranking (v2.0+)
    if self.graph_enabled:
        graph_scores = self._graph_rank(
            keyword_candidates,
            semantic_candidates,
            context
        )

    # Phase 4: Fusion ranking
    return self._fuse_results(
        keyword_candidates,
        semantic_candidates,
        graph_scores
    )
```

#### 2.3 Validation
```python
def validate_skill(self, skill_yaml: str) -> ValidationResult:
    # Pydantic schema validation
    # Tool availability check
    # Permission coherence check
    # Cost estimate sanity check
```

---

### 3. Budget Manager

**Purpose:** Track and enforce cost/token limits

**File:** `skillos/kernel/budget_manager.py`

**Features:**

#### 3.1 Pre-Execution Check
```python
def check_before_call(
    self,
    user_id: str,
    estimated_tokens: int,
    estimated_cost: float
) -> BudgetCheckResult:

    current_usage = self.get_usage(user_id, window="daily")

    # Check token limit
    if current_usage.tokens + estimated_tokens > self.limits.max_tokens_daily:
        return BudgetCheckResult(
            allowed=False,
            reason="daily_token_limit_exceeded"
        )

    # Check cost limit
    if current_usage.cost + estimated_cost > self.limits.max_cost_daily:
        return BudgetCheckResult(
            allowed=False,
            reason="daily_cost_limit_exceeded"
        )

    return BudgetCheckResult(allowed=True)
```

#### 3.2 Post-Execution Tracking
```python
def record_usage(
    self,
    request_id: str,
    user_id: str,
    tokens_used: int,
    cost_usd: float
):
    # Store in DB
    # Update Redis counters
    # Trigger alerts if approaching limits
```

#### 3.3 Degradation Policy
```python
def get_model_for_budget(
    self,
    user_id: str,
    task_complexity: float
) -> ModelConfig:

    remaining_budget = self.get_remaining_budget(user_id)

    # If budget low, use cheaper model
    if remaining_budget < 0.10:  # $0.10
        return ModelConfig(
            provider="gemini",
            model="gemini-2.0-flash-thinking-exp",
            max_tokens=4000
        )

    # Normal budget → premium model
    return ModelConfig(
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        max_tokens=8000
    )
```

---

### 4. Policy Engine

**Purpose:** Centralized authorization and policy enforcement

**File:** `skillos/policies/engine.py`

**Policy Definition (YAML):**
```yaml
policies:
  - id: "zakupki_read_only"
    description: "Allow zakupki skills for read operations only"
    rules:
      - resource: "skill:zakupki.*"
        action: "execute"
        effect: "allow"
        conditions:
          - field: "skill.capabilities.write"
            operator: "equals"
            value: false

  - id: "no_delete_without_approval"
    description: "Block all delete operations unless approved"
    rules:
      - resource: "skill:*"
        action: "execute"
        effect: "deny"
        conditions:
          - field: "skill.capabilities.delete"
            operator: "equals"
            value: true
          - field: "context.approval_status"
            operator: "not_equals"
            value: "approved"
```

**Enforcement:**
```python
def check_policy(
    self,
    user_context: UserContext,
    skill: SkillMetadata,
    action: str
) -> PolicyDecision:

    # Evaluate all applicable policies
    decisions = []
    for policy in self.policies:
        if policy.matches(skill, user_context):
            decision = policy.evaluate(skill, user_context, action)
            decisions.append(decision)

    # Default deny if no explicit allow
    if not any(d.effect == "allow" for d in decisions):
        return PolicyDecision(
            allowed=False,
            reason="no_matching_allow_policy"
        )

    # Explicit deny overrides allow
    if any(d.effect == "deny" for d in decisions):
        return PolicyDecision(
            allowed=False,
            reason=next(d.reason for d in decisions if d.effect == "deny")
        )

    return PolicyDecision(allowed=True)
```

---

### 5. Tool Wrapper

**Purpose:** Execute skills with safety guarantees

**File:** `skillos/tools/wrapper.py`

**Execution Flow:**
```python
def execute(
    self,
    skill: SkillMetadata,
    params: Dict,
    user_context: UserContext
) -> Result:

    # 1. Policy check
    policy_decision = self.policy_engine.check_policy(
        user_context,
        skill,
        action="execute"
    )
    if not policy_decision.allowed:
        return Result(
            status="policy_denied",
            error=policy_decision.reason
        )

    # 2. Rate limit check
    if not self.rate_limiter.check(skill.skill_id, user_context.user_id):
        return Result(
            status="rate_limited",
            error="too_many_requests"
        )

    # 3. Budget check
    budget_check = self.budget_manager.check_before_call(
        user_context.user_id,
        skill.cost_estimate.tokens,
        skill.cost_estimate.usd
    )
    if not budget_check.allowed:
        return Result(
            status="budget_exceeded",
            error=budget_check.reason
        )

    # 4. HITL check (if high risk)
    if skill.risk_factors.base_risk > 10:
        approval = self.hitl_gate.request_approval(
            skill,
            params,
            user_context
        )
        if not approval.granted:
            return Result(status="approval_required")

    # 5. Execute
    try:
        start_time = time.time()
        output = self._execute_skill(skill, params, user_context)
        latency_ms = (time.time() - start_time) * 1000

        # 6. Record usage
        self.budget_manager.record_usage(
            request_id=user_context.request_id,
            user_id=user_context.user_id,
            tokens_used=output.tokens_used,
            cost_usd=output.cost_usd
        )

        # 7. Log event
        self.logger.info(
            "skill_executed",
            skill_id=skill.skill_id,
            latency_ms=latency_ms,
            status="success"
        )

        return Result(
            status="success",
            output=output.data,
            metadata={
                "latency_ms": latency_ms,
                "tokens_used": output.tokens_used,
                "cost_usd": output.cost_usd
            }
        )

    except Exception as e:
        # Circuit breaker logic
        self.circuit_breaker.record_failure(skill.skill_id)

        return Result(
            status="error",
            error=str(e)
        )
```

---

### 6. HITL Gate (Human-in-the-Loop)

**Purpose:** Require human approval for risky operations

**File:** `skillos/tools/hitl_gate.py`

**Features:**

#### 6.1 Approval Request
```python
def request_approval(
    self,
    skill: SkillMetadata,
    params: Dict,
    user_context: UserContext
) -> ApprovalRequest:

    # Create approval request
    request = ApprovalRequest(
        id=generate_id(),
        skill_id=skill.skill_id,
        params=params,
        user_id=user_context.user_id,
        risk_level=skill.risk_factors.base_risk,
        preview=self._generate_preview(skill, params),
        status="pending"
    )

    # Store in DB
    self.db.save_approval_request(request)

    # Notify user (email, Telegram, webhook)
    self.notifier.send_approval_request(request)

    return request
```

#### 6.2 Approval Webhook
```python
@app.post("/api/approvals/{approval_id}/approve")
def approve_request(approval_id: str, token: str):
    # Validate token
    # Update status
    # Resume execution
```

---

### 7. Circuit Breaker

**Purpose:** Prevent cascading failures

**File:** `skillos/tools/circuit_breaker.py`

**States:**
- CLOSED: Normal operation
- OPEN: Failing, block requests
- HALF_OPEN: Testing recovery

**Logic:**
```python
class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60  # seconds
    ):
        self.failure_count = {}
        self.state = {}  # skill_id → CircuitState

    def check(self, skill_id: str) -> bool:
        state = self.get_state(skill_id)

        if state == CircuitState.OPEN:
            # Check if timeout expired
            if self._timeout_expired(skill_id):
                self.state[skill_id] = CircuitState.HALF_OPEN
                return True  # Allow one test request
            return False  # Block

        return True  # CLOSED or HALF_OPEN

    def record_success(self, skill_id: str):
        self.failure_count[skill_id] = 0
        self.state[skill_id] = CircuitState.CLOSED

    def record_failure(self, skill_id: str):
        self.failure_count[skill_id] = self.failure_count.get(skill_id, 0) + 1

        if self.failure_count[skill_id] >= self.failure_threshold:
            self.state[skill_id] = CircuitState.OPEN
            self.logger.warning(
                "circuit_breaker_opened",
                skill_id=skill_id
            )
```

---

### 8. Idempotency Manager

**Purpose:** Prevent duplicate executions

**File:** `skillos/tools/idempotency.py`

**Strategy:**
```python
def execute_idempotent(
    self,
    idempotency_key: str,
    skill: SkillMetadata,
    params: Dict,
    user_context: UserContext
) -> Result:

    # Check if already executed
    cached_result = self.cache.get(idempotency_key)
    if cached_result:
        self.logger.info(
            "idempotent_cache_hit",
            idempotency_key=idempotency_key
        )
        return cached_result

    # Execute
    result = self.tool_wrapper.execute(skill, params, user_context)

    # Cache result (24 hour TTL)
    if result.status == "success":
        self.cache.set(
            idempotency_key,
            result,
            ttl=86400
        )

    return result
```

---

## 🗄️ Data Architecture

### Storage Strategy

| Data Type | Storage | Reason |
|-----------|---------|--------|
| Skill Metadata | Postgres (JSONB) | Structured + flexible |
| Execution Logs | Postgres (partitioned) | Query + analytics |
| Skill Embeddings | Qdrant (vectors) | Semantic search |
| Skill Dependencies | Neo4j (graph) | Relationship traversal |
| Cache | Redis | Fast read/write |
| Rate Limits | Redis | TTL support |
| User Sessions | Redis | Ephemeral |

---

### Database Schemas

#### Postgres

**skills table:**
```sql
CREATE TABLE skills (
    skill_id VARCHAR(255) PRIMARY KEY,
    version VARCHAR(50) NOT NULL,
    domain VARCHAR(100),
    name VARCHAR(255),
    metadata JSONB NOT NULL,
    embedding_synced BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_skills_domain ON skills(domain);
CREATE INDEX idx_skills_metadata ON skills USING GIN(metadata);
```

**execution_logs table:**
```sql
CREATE TABLE execution_logs (
    id BIGSERIAL PRIMARY KEY,
    request_id VARCHAR(100) UNIQUE NOT NULL,
    user_id VARCHAR(100),
    tenant_id VARCHAR(100),
    query TEXT NOT NULL,

    -- Skill execution
    skill_id VARCHAR(255),
    skill_version VARCHAR(50),
    mode VARCHAR(50),  -- SINGLE | PARALLEL | PIPELINE

    -- Results
    status VARCHAR(50),  -- success | error | budget_exceeded | etc
    result JSONB,
    error TEXT,

    -- Metrics
    tokens_used INTEGER,
    cost_usd DECIMAL(10, 6),
    latency_ms INTEGER,

    -- Metadata
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Monthly partitions
CREATE TABLE execution_logs_2026_01 PARTITION OF execution_logs
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');

CREATE INDEX idx_execution_logs_user ON execution_logs(user_id, created_at);
CREATE INDEX idx_execution_logs_skill ON execution_logs(skill_id, created_at);
CREATE INDEX idx_execution_logs_status ON execution_logs(status);
```

**budget_usage table:**
```sql
CREATE TABLE budget_usage (
    id BIGSERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100),
    request_id VARCHAR(100),

    tokens_used INTEGER NOT NULL,
    cost_usd DECIMAL(10, 6) NOT NULL,

    window_type VARCHAR(20),  -- hourly | daily | monthly
    window_start TIMESTAMP NOT NULL,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_budget_usage_user_window ON budget_usage(user_id, window_start);
```

**approval_requests table:**
```sql
CREATE TABLE approval_requests (
    id VARCHAR(100) PRIMARY KEY,
    skill_id VARCHAR(255) NOT NULL,
    user_id VARCHAR(100) NOT NULL,

    params JSONB NOT NULL,
    preview TEXT,
    risk_level INTEGER,

    status VARCHAR(50),  -- pending | approved | rejected | expired
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP
);

CREATE INDEX idx_approval_requests_user_status ON approval_requests(user_id, status);
```

---

#### Neo4j (Skill Graph - v2.0+)

**Nodes:**
```cypher
// Skill node
CREATE (s:Skill {
    skill_id: "zakupki.search_tenders",
    domain: "zakupki",
    version: "1.0.0",
    capabilities: ["read", "external_api"]
})

// Tool node
CREATE (t:Tool {
    name: "zakupki_api",
    type: "external_api"
})
```

**Relationships:**
```cypher
// Skill uses Tool
CREATE (s:Skill)-[:USES {required: true}]->(t:Tool)

// Skill depends on Skill (for pipeline)
CREATE (s1:Skill)-[:DEPENDS_ON {order: 1}]->(s2:Skill)

// Skill similar to Skill (semantic)
CREATE (s1:Skill)-[:SIMILAR_TO {score: 0.85}]->(s2:Skill)
```

**Queries:**
```cypher
// Find skills that can be composed
MATCH (s1:Skill)-[:DEPENDS_ON]->(s2:Skill)
WHERE s1.domain = "zakupki"
RETURN s1, s2

// Find alternative skills
MATCH (s:Skill {skill_id: $id})-[:SIMILAR_TO]-(alt:Skill)
WHERE alt.capabilities CONTAINS $required_capability
RETURN alt
ORDER BY alt.match_score DESC
LIMIT 3
```

---

#### Qdrant (Vector Search)

**Collection Schema:**
```python
from qdrant_client.models import VectorParams, Distance

client.create_collection(
    collection_name="skills",
    vectors_config=VectorParams(
        size=1536,  # OpenAI ada-002 or similar
        distance=Distance.COSINE
    )
)
```

**Point Structure:**
```python
{
    "id": "zakupki.search_tenders",
    "vector": [0.123, 0.456, ...],  # 1536 dimensions
    "payload": {
        "skill_id": "zakupki.search_tenders",
        "domain": "zakupki",
        "name": "Search Government Tenders",
        "description": "Search zakupki.gov.ru for tenders...",
        "tags": ["zakupki", "search", "government", "tenders"],
        "capabilities": ["read", "external_api"],
        "version": "1.0.0"
    }
}
```

**Search:**
```python
results = client.search(
    collection_name="skills",
    query_vector=embed_query("найти тендеры по ремонту дорог"),
    limit=10,
    query_filter={
        "must": [
            {"key": "capabilities", "match": {"any": ["read"]}}
        ]
    }
)
```

---

## 🔄 Execution Modes

### Mode 1: Single

**Use Case:** Simple query, single skill

**Flow:**
```
Query → Skill Selection → Execute → Return Result
```

**Example:**
```
Query: "найти тендеры по ремонту дорог"
Selected: zakupki.search_tenders
Output: List of 10 tenders
```

---

### Mode 2: Parallel

**Use Case:** Independent subtasks

**Flow:**
```
Query → Decompose → Execute All (parallel) → Aggregate Results
```

**Example:**
```
Query: "найти рейсы Москва-Сочи и отели в Сочи на 15 февраля"

Subtask 1: search_flights("Moscow", "Sochi", "2026-02-15")
Subtask 2: search_hotels("Sochi", "2026-02-15")

Execute in parallel, wait for both, aggregate
```

**Implementation:**
```python
async def execute_parallel(
    self,
    subtasks: List[ExecutionTask]
) -> ParallelResult:

    # Execute all concurrently
    results = await asyncio.gather(
        *[self._execute_task(task) for task in subtasks],
        return_exceptions=True
    )

    # Handle partial failures
    successful = [r for r in results if not isinstance(r, Exception)]
    failed = [r for r in results if isinstance(r, Exception)]

    return ParallelResult(
        successful=successful,
        failed=failed,
        aggregated=self._aggregate(successful)
    )
```

---

### Mode 3: Pipeline

**Use Case:** Sequential dependency (output of one → input of next)

**Flow:**
```
Query → Decompose → Execute Stage 1 → Extract → Execute Stage 2 → ... → Distill
```

**Example:**
```
Query: "найти тендеры по ремонту дорог и проверить соответствие требованиям"

Stage 1: search_tenders("ремонт дорог")
         Output: [tender_1, tender_2, ...]

Stage 2: check_requirements(tender_1)
         Output: {meets_requirements: true, details: ...}

Stage 3: check_requirements(tender_2)
         Output: {meets_requirements: false, details: ...}

Distill: Filter to tenders where meets_requirements=true
```

**Implementation:**
```python
def execute_pipeline(
    self,
    stages: List[PipelineStage]
) -> PipelineResult:

    context = {}

    for stage in stages:
        # Extract inputs from previous stage
        inputs = self._extract(stage.input_mapping, context)

        # Execute stage
        result = self.tool_wrapper.execute(
            skill=stage.skill,
            params=inputs,
            user_context=self.user_context
        )

        # Store in context for next stage
        context[stage.name] = result.output

    # Final distillation
    final_output = self._distill(context, stages[-1].output_mapping)

    return PipelineResult(
        stages=context,
        final_output=final_output
    )
```

---

## 🧠 Advanced Features (v2.0+)

### Skill Graph

**Purpose:** Understand relationships between skills

**Use Cases:**
1. **Dependency Resolution:** Skill A needs Skill B
2. **Similarity Detection:** Find alternative skills
3. **Composition Planning:** Build composite skills
4. **Impact Analysis:** What breaks if skill X is deprecated?

**Graph Operations:**
```python
class SkillGraph:
    def find_dependencies(self, skill_id: str) -> List[str]:
        # Return all skills this skill depends on

    def find_alternatives(self, skill_id: str) -> List[str]:
        # Return similar skills that could replace this one

    def suggest_composition(
        self,
        goal: str
    ) -> List[CompositionPlan]:
        # Use graph traversal + LLM to suggest skill combinations
```

---

### Feedback Loop

**Purpose:** Learn from usage and improve

**Components:**

#### 1. Confidence Tracking
```python
class ConfidenceTracker:
    def update(self, skill_id: str, outcome: Outcome):
        # Bayesian update of confidence score

        current = self.get_confidence(skill_id)

        if outcome == Outcome.SUCCESS:
            new_confidence = current + (1 - current) * 0.1
        elif outcome == Outcome.FAILURE:
            new_confidence = current * 0.9

        self.set_confidence(skill_id, new_confidence)
```

#### 2. Auto-Promotion
```python
class SkillPromotion:
    def check_promotion(self, skill_id: str):
        stats = self.get_stats(skill_id)

        # experimental → beta
        if (stats.executions > 10 and 
            stats.success_rate > 0.80 and
            stats.status == "experimental"):
            self.promote(skill_id, "beta")

        # beta → production
        if (stats.executions > 100 and
            stats.success_rate > 0.95 and
            stats.status == "beta"):
            self.promote(skill_id, "production")
```

---

### Skill Optimizer

**Purpose:** Automatically improve skill performance

**Techniques:**

#### 1. A/B Testing
```python
def run_ab_test(
    skill_id: str,
    variant_a: SkillConfig,
    variant_b: SkillConfig,
    traffic_split: float = 0.5
):
    # Route 50% to A, 50% to B
    # Measure: success rate, latency, cost
    # After N samples, pick winner
```

#### 2. Prompt Optimization (aflow-style)
```python
def optimize_prompt(
    skill_id: str,
    test_cases: List[TestCase],
    iterations: int = 50
):
    # Monte Carlo Tree Search over prompt space
    # Try variations:
    #   - More/less detail
    #   - Different phrasing
    #   - Few-shot examples
    # Measure improvement on test cases
```

#### 3. Parameter Tuning
```python
def tune_parameters(
    skill_id: str,
    param_ranges: Dict[str, Range],
    objective: str = "minimize_cost"
):
    # Grid search or Bayesian optimization
    # Find best parameters for objective
```

---

### Composition Engine

**Purpose:** Create new skills from existing ones

**Phase 1: Safe Composition (v2.0)**
```python
def compose_skill(
    name: str,
    component_skills: List[str],
    glue_logic: CompositionLogic
) -> CompositeSkill:
    # No code generation
    # Just orchestration of existing skills
    # Example:
    #   composite_skill = [
    #       search_tenders("query"),
    #       analyze_document(result[0]),
    #       check_requirements(result[1])
    #   ]
```

**Phase 2: Synthesis (Phase 4)**
```python
def synthesize_skill(
    goal: str,
    examples: List[Example]
) -> SynthesizedSkill:
    # Meta-agent creates new skill
    # 1. Search web for similar implementations
    # 2. Generate code with LLM
    # 3. Put in sandbox
    # 4. Test extensively
    # 5. Human review
    # 6. Deploy to quarantine namespace
```

---

## 🔒 Security Architecture

### Defense-in-Depth Layers

#### Layer 1: Authentication
- JWT tokens with short expiry (1 hour)
- Refresh tokens (7 days)
- API keys for server-to-server
- OAuth for third-party integrations

#### Layer 2: Authorization
- RBAC (roles + permissions)
- ABAC (attribute-based, context-aware)
- Policy engine (centralized)

#### Layer 3: Execution Safety
- Permission checks at runtime
- Sandboxing for untrusted code
- Resource limits (CPU, memory, network)

#### Layer 4: Data Protection
- Encryption at rest (AES-256)
- Encryption in transit (TLS 1.3)
- Secrets management (external vault)
- PII detection and masking

#### Layer 5: Monitoring
- Audit logs (all operations)
- Anomaly detection
- Alert on suspicious activity

---

### Threat Model

| Threat | Mitigation |
|--------|------------|
| **SQL Injection** | Parameterized queries, ORM |
| **API Key Leak** | Vault storage, rotation |
| **Prompt Injection** | Input sanitization, structured outputs |
| **Resource Exhaustion** | Rate limits, budget caps |
| **Privilege Escalation** | Principle of least privilege |
| **Data Exfiltration** | Network policies, audit logs |
| **Supply Chain Attack** | Dependency scanning, provenance |

---

## 📊 Observability

### Logging

**Structured Logs (JSON):**
```python
logger.info(
    "skill_executed",
    request_id="req_123",
    skill_id="zakupki.search_tenders",
    user_id="user_456",
    latency_ms=1234,
    tokens_used=1500,
    cost_usd=0.003,
    status="success"
)
```

**Log Levels:**
- DEBUG: Verbose, development only
- INFO: Normal operations
- WARNING: Degraded operation, non-critical
- ERROR: Failed operation, requires attention
- CRITICAL: System failure, immediate action

---

### Metrics (Prometheus)

**Key Metrics:**
```python
# Counters
requests_total = Counter("skillos_requests_total", ["status", "skill_id"])
tokens_used_total = Counter("skillos_tokens_used_total", ["user_id"])

# Histograms
request_latency = Histogram("skillos_request_latency_seconds", ["skill_id"])
skill_search_latency = Histogram("skillos_skill_search_latency_seconds")

# Gauges
active_users = Gauge("skillos_active_users")
cache_hit_rate = Gauge("skillos_cache_hit_rate")
```

---

### Tracing (Optional)

**OpenTelemetry:**
```python
with tracer.start_as_current_span("execute_skill") as span:
    span.set_attribute("skill.id", skill_id)
    span.set_attribute("user.id", user_id)

    result = tool_wrapper.execute(skill, params, context)

    span.set_attribute("result.status", result.status)
    span.set_attribute("result.latency_ms", result.metadata.latency_ms)
```

---

## 🚀 Deployment Architecture

### Development
- Local Docker Compose
- Hot-reload enabled
- Mock external APIs

### Staging
- Google Cloud Run (or similar)
- Cloud SQL (Postgres)
- Memorystore (Redis)
- Separate from production

### Production
- Kubernetes (GKE) or Cloud Run
- Multi-zone deployment
- Auto-scaling (2-20 pods)
- Blue-green deployment

---

## 📚 Technology Stack Summary

| Layer | Technology | Version | Purpose |
|-------|------------|---------|---------|
| **Language** | Python | 3.11+ | Main language |
| **Web Framework** | FastAPI | 0.109+ | API server |
| **Data Validation** | Pydantic | 2.5+ | Schema validation |
| **Database** | PostgreSQL | 15+ | Primary storage |
| **Cache** | Redis | 7+ | Caching + rate limits |
| **Vector DB** | Qdrant | 1.7+ | Semantic search |
| **Graph DB** | Neo4j | 5.15+ | Skill relationships |
| **LLM** | Gemini 2.0 Flash | - | Primary model |
| **LLM** | Claude 3.5 Sonnet | - | Fallback model |
| **Logging** | structlog | 24.1+ | Structured logging |
| **Metrics** | Prometheus | - | Monitoring |
| **Visualization** | Grafana | - | Dashboards |
| **Error Tracking** | Sentry | - | Error monitoring |
| **Container** | Docker | 24+ | Containerization |
| **Orchestration** | Kubernetes | 1.28+ | Production deployment |

---

## 🔮 Future Considerations

### Potential Enhancements (Post v4.0)

1. **Multi-region deployment** — Global presence
2. **Edge computing** — Run skills closer to data
3. **Federated learning** — Learn across tenants without data sharing
4. **Blockchain-based provenance** — Immutable skill history
5. **Web3 integration** — Smart contract execution
6. **AR/VR interfaces** — Spatial skill orchestration

---

**Document Status:** Living document, updated quarterly

**Next Review:** April 13, 2026
