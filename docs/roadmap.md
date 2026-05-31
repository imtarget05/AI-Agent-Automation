# Multi-Agent AIOps MVP Roadmap

This document tracks the implemented MVP and the work still required before a
production deployment.

## Current State

The repository contains a containerized multi-agent AIOps prototype with:

- FastAPI gateway and LangGraph orchestration.
- RAG retrieval with corrective grading and topology enrichment.
- Read-only Kubernetes and Prometheus tools with demo fallbacks.
- Guardrail input scanning, PII anonymization, and guarded email sending.
- RCA, AIOps, report, email, DevOps proposal, approval, monitoring, and
  evaluation services.
- LLM token and cost metric publishing.

The DevOps agent is proposal-only. The tool dispatcher exposes read-only
infrastructure queries. High-risk orchestration tasks are queued for operator
approval instead of being retried or applied automatically.

## Safety Model

### Implemented

- Prompt injection checks at the gateway.
- PII and secret anonymization before guarded prompts are forwarded.
- Fail-closed behavior when the guardrail service is unavailable.
- Exact-parameter approval binding for email sends, including a body hash.
- In-memory approval records for task-level and email-send workflows.
- Automatic retry blocked for critical tool, computer-use, and DevOps actions.

### Still Required

- Unify the task approval queue and email-send approval queue.
- Persist approval records and audit events in a durable database.
- Resume the original orchestration automatically after an approval decision.
- Add role-based access control and production secret management.

## Integration Status

### Implemented

- Docker Compose wiring for the MVP services.
- Kubernetes read APIs with cluster-or-demo fallback.
- Prometheus queries with live-or-demo fallback.
- Guarded SMTP-or-local-draft email flow.
- Mock GitHub and Slack adapters for local workflow demonstrations.

### Still Required

- Replace GitHub and Slack mocks with authenticated provider integrations.
- Add end-to-end tests against a disposable Kubernetes cluster.
- Validate SMTP delivery against a controlled test server.
- Add production readiness checks, backups, and operational runbooks.

## Evaluation Status

The evaluation service and CLI provide LLM-as-a-judge scoring for synthetic
fixtures. The fixtures are useful for evaluator development but do not prove
that remediation was executed in a live environment.

The vision verifier accepts a dashboard screenshot and fails closed when the
image or model response is unavailable. It does not generate a dashboard image.

## Next Milestones

1. Persist approvals and implement approval-driven orchestration resume.
2. Add integration tests for guardrail, tool service, and gateway workflows.
3. Replace mock provider adapters with controlled sandbox integrations.
4. Expand monitoring coverage and add durable audit events.
5. Run staged validation against a disposable cluster before any production use.
