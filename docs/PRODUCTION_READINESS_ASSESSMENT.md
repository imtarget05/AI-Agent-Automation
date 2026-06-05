# Production Readiness Assessment - AI-Agent-Automation

Generated: 2026-06-05

## 1. Repo Map

- `apps/gateway/`: FastAPI Gateway, LangGraph orchestrator, agent execution boundary.
- `apps/aiops_agent/`: AIOps anomaly-analysis agent.
- `apps/rca_agent/`: RCA/reflexion reasoning loop.
- `apps/report_agent/`: Incident report generation.
- `apps/email_agent/`: Email draft/send workflow through guarded tool service.
- `apps/browser/`: Browser agent using HTTP parsing and browser-use/Playwright dependencies.
- `apps/computer_use/`: Desktop automation agent.
- `apps/social/`: Facebook/Zalo/Telegram/Slack social reply services.
- `apps/devops_agent/`: DevOps analysis and remediation proposal agent.
- `services/guardrail_service/`: Prompt injection detection, PII masking, tool guard checks.
- `services/approval_service/`: Human-in-the-loop approval persistence.
- `services/rag_service/`: RAG ingestion/retrieval, Qdrant store, GraphRAG enrichment.
- `services/eval_service/`: Evaluation service.
- `shared/`: Config, LLM router, memory, guardrails, approvals, MCP, metrics, observability, cost tracking.
- `tools/`: Kubernetes, Prometheus, email, Slack, GitHub and helper tools.
- `tests/`: Unit/integration/smoke/security plus PR 1 harness fixtures/fakes.
- `infra/otel/otel-collector-config.yaml`: Local OTEL Collector config.
- `docker-compose.yml`: Full local stack with optional observability profile.
- `.env.example`: Environment template.
- `requirements.txt`: Runtime and test dependencies.
- `pytest.ini`: Pytest config.

## 2. Current Capability

| Capability | Status | Notes |
|---|---|---|
| OpenTelemetry tracing | Da co mot phan | `shared/observability/tracing.py`; Gateway, Orchestrator, AgentExecution, LLM, RCA, RAG now create spans. Remaining TODO: instrument every microservice startup and outbound HTTP automatically. |
| structured logging | Da co mot phan | `shared/observability/logging.py` JSON formatter with service/correlation fields. Gateway/critical PR 1 paths use it; some legacy services still use stdlib logging. |
| LangGraph checkpoint | Chua co | Current graph is compiled without persistent saver. TODO(PR3): AsyncPostgresSaver/local fallback. |
| pytest | Da co | Existing tests plus PR 1 fakes/fixtures. |
| mock LLM provider | Da co | `tests/fakes/fake_llm.py`. |
| token tracking | Da co mot phan | `shared/cost/token_budget.py`; LLMRouter enforces budget when workflow metadata is supplied. TODO: persistent daily/user aggregation. |
| RBAC per-agent | Chua co | TODO(PR2): policy engine and `config/agent_permissions.yaml`. |
| audit log | Chua co | TODO(PR2): immutable audit logger. |
| DLQ/retry | Co mot phan | Job store exists; no DLQ/exponential retry yet. |
| webhook Alertmanager | Chua co | TODO(PR3): `POST /webhooks/alertmanager`. |
| SSE streaming | Chua co | TODO(PR4). |
| Redis cache | Da co | Redis session/job memory exists; LLM response cache not yet implemented. |
| Qdrant isolation | Chua co | Qdrant exists but tenant isolation is not enforced. |
| PostgreSQL metadata | Da co mot phan | Approval/monitoring config exists; workflow checkpoint metadata not yet. |
| secrets management | Co mot phan | Env-based settings and production placeholder validation. TODO(PR2): secrets abstraction for Vault/AWS Secrets Manager. |
| Browser Agent Playwright | Co mot phan | Playwright/browser-use dependencies exist; production SPA wrapper is TODO(PR4). |
| RAG hierarchical chunking | Chua co | Current chunking is fixed-size; TODO(PR4). |

## 3. Risk Ranking

Critical:
- Persistent LangGraph checkpoint is missing, so restart/resume is unsafe.
- RBAC and audit log are missing for dangerous tool/action governance.
- Production budget persistence and per-user daily budget aggregation are not yet durable.

High:
- DLQ/retry is missing for async jobs.
- Native Alertmanager webhook is missing.
- Secrets management lacks a provider abstraction.
- Tenant isolation is not enforced across Redis/Qdrant/PostgreSQL.

Medium:
- SSE streaming is missing for long-running workflows.
- LLM response cache is missing.
- RAG chunking is not optimized for runbooks.
- Browser Agent needs a stronger Playwright SPA mode.

Low:
- Agent versioning/prompt rollback is missing.
- Tool schema/MCP adapter layer is not standardized.

## 4. Implementation Plan

PR 1: Observability + Testing + Cost Control
- Implemented tracing/logging/cost modules.
- Implemented fake LLM/RAG/tools and fixtures.
- Wired spans into Gateway, Orchestrator, AgentExecution, LLM Router, RCA, RAG and key LLM agents.
- Added docs: `docs/OBSERVABILITY.md`, `docs/TESTING_AGENTS.md`, `docs/COST_CONTROL.md`.
- Added optional OTEL Collector/Jaeger compose profile.

PR 2: RBAC + Secrets + Audit Log
- TODO: `config/agent_permissions.yaml`.
- TODO: policy check before every tool execution.
- TODO: `shared/config/secrets.py`.
- TODO: immutable audit event schema and writer.

PR 3: Checkpoint + DLQ + Webhook
- TODO: persistent LangGraph checkpoint.
- TODO: retry/DLQ job states and backoff.
- TODO: native Alertmanager webhook with idempotency.

PR 4: SSE + Cache + RAG + Browser Agent
- TODO: workflow event streaming.
- TODO: Redis exact LLM cache first, semantic cache later.
- TODO: Playwright SPA wrapper and safe screenshot handling.
- TODO: hierarchical runbook chunking.

PR 5: MCP + Agent Versioning + Multi-tenancy hardening
- TODO: agent version metadata/prompt rollback.
- TODO: unified `ToolSpec` registry and MCP adapter.
- TODO: tenant-aware Redis/Qdrant/PostgreSQL/audit isolation.

## TODO

- TODO(PR1 follow-up): install full requirements and run complete `pytest --cov` in a hydrated environment.
- TODO(PR2): RBAC, secrets abstraction, immutable audit log.
- TODO(PR3): checkpoint, DLQ/retry, Alertmanager webhook.
- TODO(PR4): SSE, LLM cache, Browser Playwright mode, hierarchical RAG.
- TODO(PR5): agent versioning, MCP tool schema, multi-tenancy.
