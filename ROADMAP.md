# SkillOS Roadmap: From MVP to Self-Extending OS

**Version:** 1.0  
**Last Updated:** January 13, 2026  
**Status:** Active Development

---

## 🎯 North Star Vision

**SkillOS v4.0** — Self-Extending Adaptive Multi-Agent Operating System для бизнес-автоматизации.

**Core Philosophy:**
> "Просто прописываешь нужные скиллы и инструменты — всё сразу работает"

**Key Differentiators:**
- Declarative skill definition (конфиг → работающий код за 5 минут)
- Defense-in-depth (безопасность на каждом уровне)
- Budget-aware (экономика под контролем)
- Self-improving (система учится на своих ошибках)

---

## 📅 Timeline Overview

```
MVP          v1.0         v2.0         v3.0      Phase 4
 ├────────────┼────────────┼────────────┼───────────┼────────>
Week 4    Month 3     Month 6     Month 9    Month 12
```

**Total Duration:** 12 months to full v4.0  
**First Revenue Target:** Month 3 (v1.0)  
**Break-even Target:** Month 6 (v2.0)

---

## 🚀 Phase 0: MVP (Weeks 0-4)

**Goal:** Proof of Concept — declarative approach works

**Timeline:** 4 weeks  
**Team Size:** 1 (solo)  
**Budget:** $0 (local development, free tiers)

### What We Build

#### Core Components
- [x] **Orchestrator Brain** (basic)
  - Complexity scoring
  - Risk scoring
  - Mode selection: Single only

- [x] **Skill Registry**
  - YAML-based metadata
  - Pydantic validation
  - Hot-reload

- [x] **Tool Wrappers**
  - Permission enforcement
  - Rate limiting
  - Error handling

- [x] **Budget Manager**
  - Token tracking
  - Cost tracking
  - Hard limits

- [x] **Observability (basic)**
  - Structured logging
  - Event schema
  - Basic metrics

#### Skill Library
- 10-15 hand-crafted skills for personal use cases:
  - **zakupki:** поиск тендеров, анализ документов (3 skills)
  - **oysters:** прайс-листы, логистика, калькуляции (4 skills)
  - **travel:** поиск рейсов, отели, маршруты (3 skills)
  - **finance:** курсы валют, конвертация, бюджет (3 skills)
  - **research:** web search, summarization (2 skills)

#### Storage
- **Postgres** (JSONB for metadata)
- **Redis** (cache + rate limits)
- No vector DB yet (simple keyword match)

### What We DON'T Build
- ❌ Parallel/Pipeline modes
- ❌ Skill Graph
- ❌ Semantic search
- ❌ HITL Gate
- ❌ Multi-tenancy
- ❌ Web UI (CLI only)

### Success Criteria

**Hard Requirements:**
- [ ] Add new skill in 10 minutes (YAML + Python function)
- [ ] System chooses correct skill in 80%+ cases
- [ ] Budget enforcement works (stops at limit)
- [ ] No permission bypasses
- [ ] Can solve 5 real personal tasks end-to-end

**Performance:**
- Request latency < 2s p95
- Skill selection < 100ms
- Zero crashes on basic inputs

**Developer Experience:**
- One command to add skill: `skillos add-skill travel/search_flights`
- One command to test: `skillos test travel/search_flights`
- Hot-reload works without restart

### Deliverables
1. Working CLI application
2. 15 tested skills
3. Basic documentation
4. Demo video (for feedback)

### Week-by-Week Plan

**Week 1: Foundation**
- Day 1-2: Project setup, schemas
- Day 3-4: Orchestrator Brain
- Day 5-7: Tool Wrapper + Budget Manager

**Week 2: Skills**
- Day 8-10: First 5 skills (zakupki)
- Day 11-12: Next 5 skills (oysters)
- Day 13-14: Testing framework

**Week 3: Integration**
- Day 15-17: Skill Registry + hot-reload
- Day 18-19: Error handling
- Day 20-21: Observability

**Week 4: Polish**
- Day 22-23: Bug fixes
- Day 24-25: Documentation
- Day 26-28: Real use case validation

### Go/No-Go Decision

**GO if:**
- All 5 hard requirements met
- Positive personal experience ("я хочу это использовать каждый день")
- Clear path to adding more skills

**NO-GO if:**
- Too complex to add skills (>30 min)
- Accuracy <70%
- Constant bugs/crashes

---

## 🏗️ Phase 1: v1.0 Production-Ready (Months 1-3)

**Goal:** Enterprise-grade core + first B2B clients

**Timeline:** 3 months  
**Team Size:** 1-2 people  
**Target Revenue:** $1,000 MRR

### What We Add

#### Execution Modes
- ✅ Single (from MVP)
- 🆕 **Parallel** — concurrent agent execution
- 🆕 **Pipeline** — sequential with Extract & Distill

#### Skill Discovery
- 🆕 **Semantic Search** (Qdrant)
- 🆕 **Tag-based filtering** (manual tags)
- Simple skill index (no graph yet)

#### Defense-in-Depth (Full)
- 🆕 **HITL Gate** — human approval for risky ops
- 🆕 **Circuit Breaker** (per-tenant)
- 🆕 **Idempotency Manager**
- 🆕 **Multi-tenant cache isolation**

#### Policy Engine
- 🆕 **Central policy checker** (RBAC + ABAC)
- Declarative policies (YAML)
- Single source of truth

#### Skill Debugger v1
- 🆕 **Dry-run mode**
- 🆕 **Step-by-step execution**
- 🆕 **Performance profiling**
- Input/output inspection

#### Infrastructure
- 🆕 **FastAPI** web service
- 🆕 **Multi-tenancy** support
- 🆕 **API authentication** (JWT)
- 🆕 **Webhook support**

### Skill Library Expansion
- 30-50 curated skills
- Skill versioning (v1.0.0 format)
- Deprecation workflow
- Community contributions (via PR)

### Testing & CI/CD
- Unit tests for each skill
- Integration tests for modes
- Skill validation pipeline
- Canary deployment (10% → 50% → 100%)

### Implementation Status (repo)
- [x] Parallel + pipeline execution modes
- [x] Scheduling, webhook CLI, idempotency
- [x] Semantic + tag routing, routing cache
- [x] Approval gate, circuit breaker, RBAC/ABAC policy engine
- [x] Debugger (dry-run, trace, profiling, step-through)
- [x] Multi-tenancy + JWT auth + FastAPI service
- [x] FastAPI async handlers + thread pool for blocking work
- [x] Skill semver validation + deprecation workflow + validation pipeline


### Success Criteria

**Product:**
- [ ] 3 B2B clients using in production
- [ ] Uptime > 99.5%
- [ ] Skill search latency < 50ms p95
- [ ] Add skill in 5 minutes (including tests)
- [ ] API rate: 1000 req/hour sustained

**Business:**
- [ ] $1,000 MRR from 3 clients
- [ ] NPS > 40
- [ ] <5% churn

**Technical:**
- [ ] Zero security incidents
- [ ] <10 P0 bugs per month
- [ ] Deployment time <10 minutes

### Month-by-Month Plan

**Month 1: Modes + Search**
- Week 1-2: Parallel mode
- Week 3: Pipeline mode
- Week 4: Qdrant integration

**Month 2: Defense + Polish**
- Week 5-6: HITL + Circuit Breaker
- Week 7: Policy Engine
- Week 8: Multi-tenancy

**Month 3: Go-to-Market**
- Week 9-10: API polish + docs
- Week 11: First client onboarding
- Week 12: Feedback iteration

### Deliverables
1. Production-ready SaaS
2. 50 skills
3. Full API documentation
4. Client onboarding guide
5. Case studies (3x)

### Go/No-Go Decision

**GO to v2.0 if:**
- 3+ paying clients
- Positive feedback ("can't live without it")
- Clear demand for advanced features

**PIVOT if:**
- <2 paying clients
- Constant churn
- Feature requests all over the map (no clear pattern)

---

## 🧠 Phase 2: v2.0 Smart Optimization (Months 4-6)

**Goal:** Self-learning system + scale to 200 skills

**Timeline:** 3 months  
**Team Size:** 2-3 people  
**Target Revenue:** $10,000 MRR

### What We Add

#### Skill Graph
- 🆕 **Neo4j** for relationships
- 🆕 Auto-discovery of dependencies
- 🆕 Graph-based planning
- Justified at 100+ skills

#### Feedback Loop (Advanced)
- 🆕 **Confidence tracking**
- 🆕 **Auto-promotion** (experimental → beta → production)
- 🆕 **Skill improvement suggestions**

#### Skill Optimizer (aflow-style)
- 🆕 **A/B testing** for skills
- 🆕 **Prompt optimization**
- 🆕 **Parameter tuning** (MCTS)
- 🆕 **Planning optimization**

#### Composition Engine (Safe Self-Extension)
- 🆕 **Composite skills** from existing ones
- No code generation yet
- Human approval required
- Versioned compositions

#### Advanced Caching
- 🆕 **3-level cache** (user/role/tenant)
- 🆕 **Semantic deduplication**
- 🆕 **Smart invalidation**

### Skill Library
- 100-200 skills
- Auto-tagging via LLM
- Skill marketplace (community)
- Skill analytics dashboard

### Success Criteria

**Product:**
- [ ] 20+ paying clients
- [ ] Skill search < 20ms p95 (200 skills)
- [ ] Cache hit rate > 40%
- [ ] Composite skills created in 2 minutes

**Business:**
- [ ] $10,000 MRR
- [ ] Average contract: $500/month
- [ ] NPS > 50

**Technical:**
- [ ] Graph queries < 10ms
- [ ] 99.9% uptime

### Deliverables
1. Skill Graph visualization
2. Optimizer dashboard
3. Marketplace v1
4. 200 skills

---

## 🔮 Phase 3: v3.0 Proactive Intelligence (Months 7-9)

**Goal:** System anticipates user needs

**Timeline:** 3 months  
**Target Revenue:** $25,000 MRR

### What We Add

#### Proactive Mode (Controlled)
- 🆕 **Context monitoring** (opt-in only)
- 🆕 **Calendar integration**
- 🆕 **Opportunity detection**
- 🆕 **Anti-fatigue mechanisms**

#### Session Management
- 🆕 **Multi-turn conversations**
- 🆕 **Context accumulation**
- 🆕 **Long-term user memory**

#### Business Analytics
- 🆕 **ROI tracking per skill**
- 🆕 **Usage patterns**
- 🆕 **Optimization recommendations**

### Privacy & Compliance
- GDPR compliance toolkit
- Data minimization
- Retention policies
- Consent management

### Success Criteria
- [ ] 30% users enable proactive mode
- [ ] Proactive suggestion acceptance > 50%
- [ ] Zero GDPR violations

---

## 🤖 Phase 4: Self-Extension (Months 10-12)

**Goal:** System extends itself safely

**Timeline:** 3 months  
**Target Revenue:** $50,000 MRR

### What We Add

#### Meta-Agent (Controlled)
- 🆕 **Skill synthesis via composition** (Phase 1)
- 🆕 **Web search for examples** (Phase 2)
- 🆕 **LLM code generation** (Phase 3)

#### Sandbox Service (Separate!)
- 🆕 **Docker/Firecracker isolation**
- 🆕 **gRPC API**
- 🆕 **Resource limits**
- 🆕 **Network isolation**

#### Skill Quarantine
- 🆕 **Separate namespace** for synthesized skills
- 🆕 **Extensive testing** (20+ dry-runs)
- 🆕 **Code review workflow**
- 🆕 **Signing & versioning**

#### Supply Chain Security
- 🆕 **License compliance checking**
- 🆕 **Vulnerability scanning**
- 🆕 **Provenance tracking**

### Success Criteria
- [ ] 10% new skills auto-created
- [ ] Zero security incidents
- [ ] Synthesized skills success rate > 70%

---

## 📊 Key Metrics Dashboard

| Metric | MVP | v1.0 | v2.0 | v3.0 | Phase 4 |
|--------|-----|------|------|------|---------|
| **Skills** | 15 | 50 | 200 | 300 | 500 |
| **Clients** | 0 | 3 | 20 | 50 | 100 |
| **MRR** | $0 | $1k | $10k | $25k | $50k |
| **Team Size** | 1 | 2 | 3 | 4 | 5 |
| **Uptime** | 95% | 99.5% | 99.9% | 99.9% | 99.95% |
| **Search Latency** | 100ms | 50ms | 20ms | 15ms | 10ms |
| **Cache Hit Rate** | 0% | 15% | 40% | 50% | 60% |

---

## 🎯 Strategic Decisions

### What We Will NOT Build

Even in v4.0, we explicitly exclude:

1. **General-purpose AI** — focus on business automation only
2. **Consumer product** — B2B only
3. **No-code UI builder** — developers are our users
4. **Multi-region deployment** — single region until $100k MRR
5. **On-premise** — cloud-only until clear enterprise demand

### When to Pivot

**Red flags** that indicate need for pivot:

1. **Churn > 10%** for 2 consecutive months
2. **<$5k MRR by Month 6** (v2.0)
3. **Feature requests** pointing to completely different product
4. **Competitors** crushing us with simpler solution

**Potential pivots:**
- Niche focus (only legal, only finance)
- Developer tool (vs. end-user product)
- Open-source + enterprise (vs. pure SaaS)

---

## 💡 Risk Mitigation

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Self-extension creates security hole | High | Critical | Sandbox service, quarantine namespace |
| Graph doesn't scale to 1000+ skills | Medium | High | Start with 200, measure, optimize |
| LLM costs explode | Medium | High | Budget Manager, degradation policies |
| Proactive mode privacy concerns | High | Critical | Opt-in only, data minimization |

### Business Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| No product-market fit | Medium | Critical | Early B2B pilots, rapid iteration |
| Competition from OpenAI/Anthropic | High | High | Focus on enterprise features (compliance, control) |
| Too complex for target users | Medium | High | Excellent docs, templates, examples |

---

## 🏁 Definition of Done (Final v4.0)

**Product is DONE when:**

1. ✅ System can extend itself safely (Meta-Agent works)
2. ✅ 500+ skills in library
3. ✅ 100+ paying enterprise clients
4. ✅ $50k+ MRR
5. ✅ 99.95% uptime
6. ✅ <10ms skill search latency
7. ✅ Zero security incidents in last 6 months
8. ✅ Proactive mode adoption >30%
9. ✅ Auto-generated skills success rate >70%
10. ✅ NPS >60

**At this point:** SkillOS v4.0 is a self-sustaining, self-improving business automation OS.

---

**Next Steps:** See [MVP_SPEC.md](./MVP_SPEC.md) for detailed 4-week plan.
