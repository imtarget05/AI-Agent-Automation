# 🤖 Multi-Agent AIOps Platform

> **Production-grade autonomous incident response** — detects anomalies, traces root causes, drafts reports, and routes human approvals through a microservices orchestration layer.

[![CI](https://github.com/your-org/AI-Agent-Automation/actions/workflows/ci-agent.yml/badge.svg)](https://github.com/your-org/AI-Agent-Automation/actions)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green.svg)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange.svg)](https://github.com/langchain-ai/langgraph)

---

## What makes this different

Most AI agent portfolios show "chat with PDF". This platform solves a real production problem:

| Capability | Why it matters |
|---|---|
| **Guardrail + Approval Flow** | Agents don't act blindly — dangerous ops (kubectl delete, etc.) require human approval |
| **Resilience & Circuit Breaker** | LLM router with exponential backoff and auto-fallback (GPT-4o → Claude → Ollama) |
| **Search Fallback** | Browser agent with intelligent DDG fallback and LLM-assisted HTML parsing |
| **Optional MCP Tools** | Lazy STDIO MCP integrations with guardrail and approval checks |
| **Curated Open-source Knowledge** | Index selected cloned README files into vector memory without importing foreign runtimes |
| **Optional AgentScope + Claw** | Explicit opt-in adapters; unavailable runtimes fail closed instead of returning mock success |
| **Corrective RAG** | Query expansion → vector retrieval → LLM relevance grading → hallucination check |
| **Security First** | Automated PII masking, production secret validation, and dependency auditing |
| **Reflexion-style RCA** | Root cause agent reasons in a loop (up to N steps) with real tool observations |
| **Evaluation Service** | Faithfulness score, relevance score, trajectory correctness — you can *measure* the agent |
| **Async Job Persistence** | Long-running tasks stored in Redis; clients poll `GET /tasks/{job_id}` |

---

## Architecture — Incident End-to-End

```
┌────────────────────────────────────────────────────────────────┐
│                        CLIENT / ALERT SOURCE                   │
│              POST /incident/analyze  ·  POST /execute          │
└───────────────────────────┬────────────────────────────────────┘
                            │
                    ┌───────▼────────┐
                    │    GATEWAY     │  :8000
                    │  FastAPI + JWT │
                    │  Rate · CORS   │
                    └──────┬─────────┘
                           │ LangGraph orchestration
          ┌────────────────┼────────────────────────────┐
          │                │                            │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌────────────────▼──┐
   │  GUARDRAIL  │  │  AIOPS      │  │   RAG SERVICE     │
   │  :8010      │  │  AGENT :8013│  │   :8007           │
   │ Prompt inj. │  │ Anomaly     │  │ Query expansion   │
   │ PII masking │  │ detection   │  │ Re-ranking        │
   │ Approval    │  │ via metrics │  │ LLM grading       │
   └──────┬──────┘  └──────┬──────┘  └────────────────┬──┘
          │                │                           │
   ┌──────▼──────┐  ┌──────▼──────┐  ┌───────────────▼───┐
   │  APPROVAL   │  │  RCA AGENT  │  │   TOOL SERVICE    │
   │  SERVICE    │  │  :8014      │  │   :8008           │
   │  :8011      │  │ Reflexion   │  │ Prometheus (real) │
   │ Human HITL  │  │ loop ≤N     │  │ K8s (real/MOCK)   │
   └─────────────┘  └──────┬──────┘  └───────────────────┘
                           │
               ┌───────────┴──────────┐
        ┌──────▼──────┐       ┌───────▼───────┐
        │ REPORT AGENT│       │  EMAIL AGENT  │
        │  :8012      │       │  :8009        │
        │ MD/HTML from│       │ Incident email│
        │ real RCA out│       │ draft/send    │
        └─────────────┘       └───────────────┘

Infrastructure:
  Redis   :6379  — Session memory · Async job store (TTL 1h)
  Qdrant  :6333  — RAG vector store · Long-term agent memory
  Postgres:5432  — Metrics persistence (prod) / SQLite (dev)
  n8n     :5678  — Workflow automation triggers
```

---

## Quick Start (5 minutes)

### Prerequisites
- Docker + Docker Compose
- Python 3.12+
- OpenAI or Anthropic API key

```bash
# 1. Clone and configure
git clone https://github.com/your-org/AI-Agent-Automation.git
cd AI-Agent-Automation
cp .env.example .env
# → Edit .env: set OPENAI_API_KEY or ANTHROPIC_API_KEY

# 2. Start dev stack (no real Prometheus/K8s needed — mock data built-in)
make dev

# 3. Verify all services are healthy
make health-all

# 4. Ingest runbooks into RAG
make ingest-docs

# 5. Run the end-to-end demo
make demo
```

### Access points
| Service | URL | Notes |
|---|---|---|
| **Gateway API** | http://localhost:8000/docs | Swagger UI — try it live |
| **Dashboard** | http://localhost:8006 | Real-time metrics |
| **Monitoring** | http://localhost:8005 | Agent observability |
| **API Key (dev)** | `dev-secret-key-change-in-prod` | Set in `Bearer` header |

---

## Key Endpoints

```bash
export KEY="dev-secret-key-change-in-prod"
export GW="http://localhost:8000"

# --- Incident analysis (sync) ---
curl -X POST $GW/incident/analyze \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "incident_data": {
      "service": "payment-api",
      "severity": "critical",
      "message": "CPU 96%, latency 4.8s, OOMKilled"
    }
  }'

# --- Async task + polling ---
JOB=$(curl -sX POST $GW/execute-async \
  -H "Authorization: Bearer $KEY" \
  -d '{"user_input": "Find root cause of payment-api degradation"}' \
  -H "Content-Type: application/json" | jq -r .job_id)

curl $GW/tasks/$JOB -H "Authorization: Bearer $KEY"

# --- Human approval for dangerous ops ---
curl -X POST $GW/approvals \
  -H "Authorization: Bearer $KEY" \
  -d '{"tool_name":"kubectl","action":"delete_pod","parameters":{"pod":"payment-api-7d88c44f"}}'
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | Primary LLM (GPT-4o) |
| `ANTHROPIC_API_KEY` | ✅ | Fallback LLM (Claude) |
| `API_SECRET_KEY` | ✅ | Gateway auth token |
| `DATABASE_URL` | ✅ | PostgreSQL (prod) / SQLite (dev) |
| `REDIS_URL` | ✅ | Session + job store |
| `QDRANT_URL` | ✅ | Vector DB for RAG |
| `PROMETHEUS_URL` | ⬜ | Real metrics (MOCK if unset) |
| `LANGSMITH_API_KEY` | ⬜ | LLM tracing (optional) |
| `SMTP_SERVER` | ⬜ | Email sending (dev: saves to docs/) |

> See [`.env.example`](.env.example) for full reference with placeholders.

---

## Testing

```bash
make test           # Full suite with coverage report
make test-unit      # Unit tests only (no Docker required)
make smoke          # Smoke tests against local gateway
make smoke-staging  # Smoke tests against STAGING_GATEWAY_URL
```

Test coverage targets:
- **Unit** — `shared/`, `tools/`, individual agents
- **Integration** — incident pipeline, async job polling, approval workflow
- **Smoke** — 13 live endpoint checks (gateway, auth, guardrail, session)

---

## CI/CD — 3-Agent Pipeline

```
Push → CI Agent → Staging Agent → Production Agent
          ↓             ↓                ↓
     lint+test    deploy+smoke    blue/green + rollback
     13 images    gate PR         stable tag + release
```

Workflows: [`.github/workflows/`](.github/workflows/)

---

## Project Structure

```
AI-Agent-Automation/
├── apps/
│   ├── gateway/        # Entry point — auth, routing, LangGraph orchestrator
│   ├── aiops_agent/    # Anomaly detection from Prometheus metrics
│   ├── rca_agent/      # Reflexion loop root cause analysis
│   ├── devops_agent/   # K8s / CI-CD failure analysis
│   ├── report_agent/   # Structured incident report from real RCA output
│   ├── email_agent/    # Incident email drafting and sending
│   ├── monitoring/     # Agent metrics collection
│   └── dashboard/      # Real-time observability UI
├── services/
│   ├── guardrail_service/  # Prompt injection, PII masking, approval routing
│   ├── approval_service/   # Human-in-the-loop approval store
│   ├── rag_service/        # Corrective RAG with re-ranking and grading
│   └── eval_service/       # Faithfulness + trajectory evaluation (LLM-as-judge)
├── shared/
│   ├── config.py       # Centralized Settings (pydantic-settings)
│   ├── llm.py          # LLM router — GPT-4o → Claude fallback → Ollama
│   ├── memory.py       # Session memory (Redis) + long-term memory (Qdrant)
│   ├── job_store.py    # Redis-backed async job persistence
│   ├── guardrails.py   # Guardrail client
│   └── models.py       # Shared Pydantic models
├── tools/
│   ├── k8s.py          # Kubernetes API (real + MOCK fallback)
│   ├── prometheus.py   # PromQL queries (real + MOCK fallback)
│   └── email.py        # SMTP email tool
├── tests/
│   ├── test_integration.py  # Incident pipeline, async jobs, approvals
│   ├── smoke/               # Live gateway smoke tests
│   └── production/          # Production-only verification tests
├── demo.py             # End-to-end demo (run: make demo)
├── docker-compose.yml         # Production stack
├── docker-compose.dev.yml     # Dev override (mock infra, SQLite, hot-reload)
└── Makefile            # All commands: make dev | test | smoke | demo
```

---

## Design Decisions

**Why LangGraph over AutoGen?** — LangGraph gives explicit control over the state machine. Each node transition is deterministic and inspectable. AutoGen's conversational model is harder to audit for production safety requirements.

**Why Qdrant over Pinecone?** — Self-hosted, zero cost, and the filtering API matches our namespace-based memory design. Pinecone's serverless tier has cold-start latency that breaks real-time incident response SLAs.

**Why separate Guardrail service?** — Decoupling safety from business logic means we can update injection patterns, add PII rules, or A/B test guardrail strictness without touching agent code. It also creates a clear audit boundary.

**Mock-first tool design** — Every tool (K8s, Prometheus, email) tries the real API first and falls back to realistic mock data. This means the demo runs out of the box while production behaviour is identical — just with live data. Mocks are clearly labelled `# MOCK:`.

---

## License

MIT
