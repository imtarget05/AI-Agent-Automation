# Testing Agents — Test Harness Guide

## Overview

PR 1 adds a testing framework that lets you write and run agent flow tests
**without any real API keys or running services**.

```
tests/
  conftest.py                    ← root pytest config + smoke-skip logic
  fakes/
    fake_llm.py                  ← FakeLLMProvider + FakeLLMRouter
    fake_rag.py                  ← FakeRAGStore + FakeRAGClient
    fake_tools.py                ← FakeToolRegistry + pre-built fakes
  fixtures/
    sample_alertmanager_payload.json
    sample_prometheus_metrics.json
    sample_runbook.md
  agents/
    test_rca_agent.py            ← RCA flow: success, fallback, budget
  cost/
    test_budget.py               ← Token/cost budget enforcement
  observability/
    test_tracing.py              ← Tracing enabled/disabled modes
  llm/
    test_router.py               ← FakeLLMRouter + model selection
  security/
    test_guardrail.py            ← Guardrail blocking + PII masking
```

---

## Running tests

```bash
# All unit tests (no API keys needed)
pytest

# With coverage report
pytest --cov=shared --cov=apps --cov-report=term-missing

# Only a specific module
pytest tests/cost/
pytest tests/agents/

# With verbose output
pytest -v tests/agents/test_rca_agent.py
```

---

## Using FakeLLMRouter in your tests

```python
from tests.fakes.fake_llm import FakeLLMRouter, make_rca_router

# Simple sequential responses
router = FakeLLMRouter(chat_responses=["Step 1 action", "FINAL_ANSWER: done"])

# Pre-built scenario: successful 2-step RCA
router = make_rca_router(steps=2, final_answer="GC pressure confirmed.")

# Simulate rate-limit on first call, succeed on second
from tests.fakes.fake_llm import FakeRateLimitError
router = FakeLLMRouter(
    chat_responses=["ignored", "FINAL_ANSWER: fallback result"],
    fail_on_chat_call=0,
    chat_error=FakeRateLimitError("429"),
)

# Inject into a component that uses llm_router:
from unittest.mock import patch
with patch("apps.rca_agent.main.llm_router", router):
    result = await call_rca_agent(...)
```

---

## Using FakeRAGStore

```python
from tests.fakes.fake_rag import FakeRAGStore

rag = FakeRAGStore(results=[
    {"text": "Runbook: restart pod to fix OOM", "score": 0.92}
])

results = await rag.search("memory leak")
assert len(results) == 1
assert rag.call_count == 1
```

---

## Using FakeToolRegistry

```python
from tests.fakes.fake_tools import FakeToolRegistry, make_k8s_registry

# Pre-built K8s fake
registry = make_k8s_registry(pods=["payment-service-abc-123"])
result = await registry.invoke("kubectl_get_pods", {"namespace": "production"})
assert result["pods"] == ["payment-service-abc-123"]

# Custom tool + simulated error
registry = FakeToolRegistry()
registry.register("email_send", error=ConnectionError("SMTP down"))
with pytest.raises(ConnectionError):
    await registry.invoke("email_send", {"to": "ops@example.com"})
```

---

## Writing a new agent test

```python
# tests/agents/test_my_agent.py
import pytest
from tests.fakes.fake_llm import FakeLLMRouter

class TestMyAgent:
    @pytest.mark.asyncio
    async def test_success_flow(self):
        router = FakeLLMRouter(chat_responses=["FINAL_ANSWER: done"])
        # inject router into your agent, run it, assert result
        ...

    @pytest.mark.asyncio
    async def test_budget_exceeded(self):
        from shared.cost.token_budget import BudgetPolicy, WorkflowBudgetTracker, BudgetExceededError
        policy = BudgetPolicy(max_llm_calls_per_workflow=1)
        tracker = WorkflowBudgetTracker("wf-test", policy=policy)
        ...
```

---

## Required test dependencies

Included in `requirements.txt`:

```
pytest==8.2.2
pytest-asyncio==0.23.7
pytest-cov==5.0.0
```

Install:

```bash
pip install -r requirements.txt
```

---

## Running without API keys

All tests in `tests/agents/`, `tests/cost/`, `tests/observability/`,
`tests/llm/`, `tests/security/` are designed to run without any external
services or API keys. They use:

- `FakeLLMRouter` instead of real LiteLLM
- `FakeRAGStore` instead of real Qdrant
- `FakeToolRegistry` instead of real Kubernetes/Prometheus
- `unittest.mock.patch` for HTTP clients

Smoke tests (`tests/smoke/`) still require a running gateway. They are
automatically skipped when the gateway is unreachable.

---

## Pytest markers

| Marker | Description |
|---|---|
| `@pytest.mark.unit` | Pure unit test, no external deps |
| `@pytest.mark.integration` | Mocked external services |
| `@pytest.mark.asyncio` | Async test (pytest-asyncio) |
| `@pytest.mark.smoke` | Requires live gateway |
| `@pytest.mark.production` | Requires production gateway |
