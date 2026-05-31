# MVP Evaluation Notes

This document records the current local verification scope. It is not a
production readiness certification.

## Verified Locally

The following checks passed on May 31, 2026:

```text
python -m pytest -q
2 passed

AST parse across apps/, services/, shared/, tools/, and tests/
55 Python files parsed

docker compose config --quiet
valid configuration

LangGraph orchestrator construction
13 graph nodes
```

Additional smoke checks verified:

- Guardrail PII anonymization does not return original PII mappings.
- Monitoring metric payloads serialize timestamps as JSON strings.
- Corrective RAG grading still runs after semantic reranking.
- Vision verification fails closed when no dashboard screenshot exists.
- Guarded email sends require an approval before delivery or local drafting.
- The tool dispatcher limits generic orchestration requests to read-only queries.

## Implemented Evaluation Components

### LLM-as-a-Judge Fixtures

`services/eval_service/evaluator.py` scores:

- RAG faithfulness.
- Answer relevance.
- Agent trajectory correctness.

`tools/run_evaluation.py` feeds representative synthetic answers into those
scorers. It exercises the evaluator only. It does not execute remediation,
restart workloads, send stakeholder email, or prove live incident recovery.

### Vision Verification

`tools/vision_verifier.py` inspects a supplied dashboard screenshot with a vision
model. Missing screenshots, model errors, and invalid model responses return a
failed verification result.

### Safety Verification

The gateway performs input guard checks before execution. The orchestrator
records approval requests for high-risk operations and blocks automatic retries
for critical tool, computer-use, and DevOps actions.

## Not Yet Validated

- Live remediation against a disposable Kubernetes cluster.
- Durable approval persistence and automatic workflow resume.
- Real GitHub and Slack provider calls.
- Production SMTP delivery.
- Load, failover, disaster recovery, and security penetration testing.
- Any fixed system accuracy score for real incidents.

## Known Local Warnings

- Pydantic class-based configuration is deprecated and should move to
  `ConfigDict` before Pydantic v3.
- LangGraph emits a pending deprecation warning for serializer defaults.
- Local tool imports may use mock-only Kubernetes mode when the Python package
  or cluster configuration is unavailable.
