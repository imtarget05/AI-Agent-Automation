# Cost Control

PR 1 adds token budget and LLM spend tracking in `shared/cost/token_budget.py`.

Budget enforcement is integrated into `shared/llm.py`. It activates when callers pass a `workflow_id` to `LLMRouter.chat(...)`. Existing callers without workflow metadata keep backward-compatible behavior.

## Environment Variables

```env
MAX_TOKENS_PER_REQUEST=20000
MAX_TOKENS_PER_WORKFLOW=80000
MAX_LLM_CALLS_PER_WORKFLOW=20
MAX_COST_PER_WORKFLOW_USD=2.00
MAX_COST_PER_USER_DAILY_USD=10.00
```

## Behavior

Before each LLM call:

- `WorkflowBudgetTracker.check_before_call(...)` blocks workflows that already exceed call/token/cost limits.

After each LLM call:

- prompt/completion tokens are recorded when provider usage metadata is available.
- estimated cost is calculated from the local cost table.
- failures are recorded with `success=false` when there is no fallback left.
- `BudgetExceededError` is raised as a hard stop and is not treated as a provider fallback condition.

Structured error shape:

```json
{
  "error": "budget_exceeded",
  "message": "Workflow exceeded configured LLM budget",
  "workflow_id": "wf-abc",
  "reason": "llm_call_limit_exceeded: 20 >= 20",
  "current_usage": {
    "total_tokens": 65000,
    "estimated_cost_usd": 1.95,
    "llm_calls": 20
  }
}
```

## Wired Paths

- Gateway Orchestrator planning and synthesis.
- RCA Agent reasoning loop.
- RAG query expansion, reranking and relevance grading.
- AIOps Agent analysis.
- DevOps Agent analysis.
- Email Agent composition.
- AgentExecution reflection LLM calls inherit workflow metadata when task context includes it.

## Usage

```python
response = await llm_router.chat(
    messages=[{"role": "user", "content": prompt}],
    task="analysis",
    workflow_id=workflow_id,
    session_id=session_id,
    agent_name="rca_agent",
    estimated_tokens=1200,
)
```

## Tests

```bash
python -m pytest tests/cost tests/agents/test_rca_agent.py tests/llm -q
```

Covered:

- within-budget calls
- workflow token exceeded
- request token exceeded
- cost exceeded
- LLM call count exceeded
- fallback usage accounting
- budget error response shape
- RCA loop budget stop via fake LLM harness

## Remaining TODO

- TODO(PR2): audit event on budget exceeded.
- TODO(PR3): persist usage records to PostgreSQL.
- TODO(PR3): Redis daily per-user aggregation.
- TODO(PR5): per-tenant budget policy.
