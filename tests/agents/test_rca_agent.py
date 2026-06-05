"""
tests/agents/test_rca_agent.py — RCA Agent flow tests
======================================================
Tests RCA reasoning without real LLM calls.
All tests use FakeLLMRouter and FakeRAGStore as drop-in replacements.

Test cases:
  1. Successful RCA completes and returns FINAL_ANSWER
  2. Provider failure → fallback provider used
  3. Reflexion loop stops at max iteration
  4. RAG retrieval context fed into RCA
  5. Budget exceeded during reasoning loop
"""

from __future__ import annotations

import re
from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

from tests.fakes.fake_llm import (
    FakeLLMRouter,
    FakeRateLimitError,
    make_rca_router,
)
from tests.fakes.fake_rag import FakeRAGStore
from shared.cost.token_budget import (
    BudgetExceededError,
    BudgetPolicy,
    WorkflowBudgetTracker,
)


# ──── Helpers ──────────────────────────────────────────────────────────────────

def _make_settings_mock(max_steps: int = 5) -> MagicMock:
    settings = MagicMock()
    settings.rca_max_reasoning_steps = max_steps
    settings.rag_service_url = "http://fake-rag:8007"
    settings.aiops_agent_service_url = "http://fake-aiops:8013"
    settings.tool_service_url = "http://fake-tool:8008"
    return settings


async def _run_rca_loop(
    instruction: str,
    llm_router: FakeLLMRouter,
    max_steps: int = 5,
    rag_store: Optional[FakeRAGStore] = None,
    budget_tracker: Optional[WorkflowBudgetTracker] = None,
) -> dict[str, Any]:
    """Minimal RCA reasoning loop that mirrors apps/rca_agent/main.py.

    This is an inline re-implementation so tests don't require the real
    service infrastructure (httpx, FastAPI, etc.).
    """
    from shared.cost.token_budget import get_tracker

    tracker = budget_tracker or get_tracker(f"test-wf-{id(instruction)}")

    system_prompt = (
        "You are an RCA expert. Available actions:\n"
        '1. RAG_SEARCH: {"action": "RAG_SEARCH", "query": "..."}\n'
        'When done, output: FINAL_ANSWER: <conclusion>'
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction},
    ]
    history: list[dict[str, Any]] = []

    for step in range(1, max_steps + 1):
        tracker.check_before_call(estimated_tokens=500)
        response = await llm_router.chat(messages, task="rca")
        tracker.record_call(
            model="fake-model",
            prompt_tokens=100,
            completion_tokens=50,
            success=True,
        )
        history.append({"step": step, "response": response})
        messages.append({"role": "assistant", "content": response})

        if "FINAL_ANSWER" in response:
            return {
                "success": True,
                "history": history,
                "final_conclusion": response,
                "steps": step,
            }

        # Simulate RAG search side-effect
        action_match = re.search(r'"action"\s*:\s*"RAG_SEARCH"', response)
        if action_match and rag_store:
            results = await rag_store.search("cpu issue")
            context = "\n".join(r["text"] for r in results)
            messages.append({"role": "user", "content": f"RAG context: {context}"})

    return {"success": False, "history": history, "reason": "max_iterations_reached"}


# ──── Tests ────────────────────────────────────────────────────────────────────

class TestRCAAgentSuccess:
    @pytest.mark.asyncio
    async def test_rca_completes_with_final_answer(self):
        """RCA loop returns success when LLM emits FINAL_ANSWER."""
        router = make_rca_router(steps=2, final_answer="GC pressure detected.")
        result = await _run_rca_loop("High CPU on payment-service", router, max_steps=5)
        assert result["success"] is True
        assert "FINAL_ANSWER" in result["final_conclusion"]
        assert result["steps"] <= 5

    @pytest.mark.asyncio
    async def test_rca_uses_rag_context(self):
        """RAG results must be incorporated into the reasoning context."""
        rag = FakeRAGStore(
            results=[{"text": "Runbook step: check GC logs.", "score": 0.9}]
        )
        router = make_rca_router(steps=2, final_answer="GC loop confirmed.")
        result = await _run_rca_loop(
            "High CPU on payment-service",
            router,
            max_steps=5,
            rag_store=rag,
        )
        assert result["success"] is True
        # At least one step triggered RAG search
        assert rag.call_count >= 1


class TestRCAAgentFallback:
    @pytest.mark.asyncio
    async def test_first_call_fails_then_fallback_succeeds(self):
        """When primary provider fails, the fallback returns a valid answer."""
        # call_index=0 raises rate-limit; call_index=1 succeeds with FINAL_ANSWER
        router = FakeLLMRouter(
            chat_responses=[
                "FINAL_ANSWER: GC pressure after fallback.",
            ],
            fail_on_chat_call=0,
            chat_error=FakeRateLimitError("429 Too Many Requests"),
        )

        # Simulate outer retry logic: catch error and retry on same router.
        # Do NOT reset — counter advanced past fail_on_call=0 after the error.
        try:
            result = await _run_rca_loop("cpu spike", router, max_steps=3)
        except FakeRateLimitError:
            result = await _run_rca_loop("cpu spike", router, max_steps=3)

        assert result["success"] is True
        assert "FINAL_ANSWER" in result["final_conclusion"]


class TestRCAReflexionLoopLimit:
    @pytest.mark.asyncio
    async def test_loop_stops_at_max_iterations(self):
        """Loop must terminate after max_steps even without FINAL_ANSWER."""
        # Router always returns an action, never a FINAL_ANSWER
        router = FakeLLMRouter(
            chat_responses=['{"action": "RAG_SEARCH", "query": "metrics"}']
        )
        result = await _run_rca_loop(
            "Investigate CPU spike",
            router,
            max_steps=3,
        )
        assert result["success"] is False
        assert result["reason"] == "max_iterations_reached"
        assert router.call_count == 3


class TestRCABudgetControl:
    @pytest.mark.asyncio
    async def test_budget_exceeded_stops_loop(self):
        """Workflow must stop with BudgetExceededError when limits are breached."""
        policy = BudgetPolicy(
            max_llm_calls_per_workflow=2,
            max_tokens_per_workflow=99999,
            max_cost_per_workflow_usd=99.0,
        )
        tracker = WorkflowBudgetTracker("test-budget-wf", policy=policy)
        router = FakeLLMRouter(
            chat_responses=['{"action": "RAG_SEARCH", "query": "x"}'] * 10
        )

        with pytest.raises(BudgetExceededError) as exc_info:
            await _run_rca_loop(
                "Investigate",
                router,
                max_steps=10,
                budget_tracker=tracker,
            )

        assert "llm_call_limit_exceeded" in str(exc_info.value)
        assert exc_info.value.workflow_id == "test-budget-wf"

    @pytest.mark.asyncio
    async def test_token_budget_exceeded(self):
        """WorkflowBudgetTracker raises when token limit is crossed."""
        policy = BudgetPolicy(
            max_tokens_per_workflow=100,
            max_llm_calls_per_workflow=99,
            max_cost_per_workflow_usd=99.0,
        )
        tracker = WorkflowBudgetTracker("test-token-wf", policy=policy)
        # Record 60 tokens
        tracker.record_call(model="gpt-4o", prompt_tokens=30, completion_tokens=30, success=True)
        # Next check should fail (60 + 500 estimated > 100)
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.check_before_call(estimated_tokens=500)

        assert "token" in str(exc_info.value).lower()
