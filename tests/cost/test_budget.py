"""
tests/cost/test_budget.py — Token budget enforcement tests
===========================================================
Tests for shared/cost/token_budget.py

Test cases:
  1. Budget within limits — no error raised
  2. Workflow token limit exceeded
  3. Workflow cost limit exceeded
  4. Workflow LLM call count exceeded
  5. Per-request token limit exceeded
  6. Fallback call still accumulates usage
  7. Budget tracker registry (get_tracker / remove_tracker)
  8. estimate_cost_usd for known + unknown models
"""

from __future__ import annotations

import pytest

from shared.cost.token_budget import (
    BudgetExceededError,
    BudgetPolicy,
    WorkflowBudgetTracker,
    estimate_cost_usd,
    get_tracker,
    remove_tracker,
)


class TestEstimateCost:
    def test_known_model(self):
        cost = estimate_cost_usd("gpt-4o", 1000)
        assert cost == pytest.approx(0.005, rel=1e-3)

    def test_mini_model(self):
        cost = estimate_cost_usd("gpt-4o-mini", 1000)
        assert cost == pytest.approx(0.00015, rel=1e-3)

    def test_free_ollama_model(self):
        cost = estimate_cost_usd("ollama/deepseek-r1:8b", 5000)
        assert cost == 0.0

    def test_unknown_model_uses_default(self):
        cost = estimate_cost_usd("unknown-mystery-model", 1000)
        assert cost > 0.0  # uses default rate


class TestBudgetWithinLimits:
    def test_no_error_when_within_limits(self):
        tracker = WorkflowBudgetTracker(
            "wf-ok",
            policy=BudgetPolicy(
                max_tokens_per_workflow=10000,
                max_llm_calls_per_workflow=5,
                max_cost_per_workflow_usd=5.0,
            ),
        )
        tracker.record_call(
            model="gpt-4o-mini",
            prompt_tokens=50,
            completion_tokens=50,
            success=True,
        )
        assert tracker.total_tokens == 100
        assert tracker.llm_calls == 1
        # No exception raised — budget not exceeded

    def test_usage_snapshot_accurate(self):
        tracker = WorkflowBudgetTracker("wf-snap")
        tracker.record_call(
            model="gpt-4o-mini", prompt_tokens=100, completion_tokens=50, success=True
        )
        snapshot = tracker.usage_snapshot()
        assert snapshot["total_tokens"] == 150
        assert snapshot["llm_calls"] == 1
        assert snapshot["estimated_cost_usd"] >= 0.0


class TestTokenBudgetExceeded:
    def test_workflow_token_limit(self):
        policy = BudgetPolicy(
            max_tokens_per_workflow=100,
            max_llm_calls_per_workflow=99,
            max_cost_per_workflow_usd=99.0,
        )
        tracker = WorkflowBudgetTracker("wf-tok", policy=policy)
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.check_before_call(estimated_tokens=101)

        assert "token" in str(exc_info.value).lower()
        assert exc_info.value.workflow_id == "wf-tok"
        assert "total_tokens" in exc_info.value.current_usage

    def test_after_recording_calls_raises_on_next_check(self):
        policy = BudgetPolicy(
            max_tokens_per_workflow=200,
            max_llm_calls_per_workflow=99,
            max_cost_per_workflow_usd=99.0,
        )
        tracker = WorkflowBudgetTracker("wf-tok2", policy=policy)
        tracker.record_call(model="gpt-4o-mini", prompt_tokens=100, completion_tokens=100, success=True)

        with pytest.raises(BudgetExceededError):
            tracker.check_before_call(estimated_tokens=100)

    def test_per_request_token_limit(self):
        policy = BudgetPolicy(max_tokens_per_request=500)
        tracker = WorkflowBudgetTracker("wf-req", policy=policy)
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.check_request_tokens(600)

        assert "request_token_limit_exceeded" in str(exc_info.value)


class TestCostBudgetExceeded:
    def test_workflow_cost_limit(self):
        policy = BudgetPolicy(
            max_tokens_per_workflow=999999,
            max_llm_calls_per_workflow=99,
            max_cost_per_workflow_usd=0.001,  # very low limit
        )
        tracker = WorkflowBudgetTracker("wf-cost", policy=policy)

        with pytest.raises(BudgetExceededError) as exc_info:
            # gpt-4o: $0.005/1k → 1000 tokens → $0.005 > $0.001
            tracker.record_call(
                model="gpt-4o",
                prompt_tokens=500,
                completion_tokens=500,
                success=True,
            )

        assert "cost" in str(exc_info.value).lower()


class TestCallCountBudgetExceeded:
    def test_llm_call_limit(self):
        policy = BudgetPolicy(
            max_tokens_per_workflow=999999,
            max_llm_calls_per_workflow=2,
            max_cost_per_workflow_usd=999.0,
        )
        tracker = WorkflowBudgetTracker("wf-calls", policy=policy)
        # First call: ok
        tracker.record_call(model="gpt-4o-mini", prompt_tokens=10, completion_tokens=10, success=True)
        # Second call: ok but post-call check will raise (2 >= 2 for next call)
        with pytest.raises(BudgetExceededError) as exc_info:
            tracker.record_call(model="gpt-4o-mini", prompt_tokens=10, completion_tokens=10, success=True)

        assert "llm_call_limit_exceeded" in str(exc_info.value)


class TestFallbackAccumulatesUsage:
    def test_fallback_call_still_counted(self):
        """Even if a call fails, usage from previous calls accumulates."""
        policy = BudgetPolicy(
            max_tokens_per_workflow=999999,
            max_llm_calls_per_workflow=99,
            max_cost_per_workflow_usd=999.0,
        )
        tracker = WorkflowBudgetTracker("wf-fallback", policy=policy)
        # Record a successful call
        tracker.record_call(
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            success=True,
        )
        # Record a failed call (fallback attempted but failed)
        tracker.record_call(
            model="gpt-4o-mini",
            prompt_tokens=50,
            completion_tokens=0,
            success=False,
            error_type="rate_limit",
        )
        assert tracker.llm_calls == 2
        assert tracker.total_tokens == 200


class TestTrackerRegistry:
    def test_get_tracker_returns_same_instance(self):
        tracker_a = get_tracker("wf-registry-1")
        tracker_b = get_tracker("wf-registry-1")
        assert tracker_a is tracker_b

    def test_remove_tracker(self):
        get_tracker("wf-registry-2")
        removed = remove_tracker("wf-registry-2")
        assert removed is not None
        # After removal, a new tracker is created
        fresh = get_tracker("wf-registry-2")
        assert fresh.llm_calls == 0

    def teardown_method(self):
        remove_tracker("wf-registry-1")
        remove_tracker("wf-registry-2")


class TestBudgetExceededErrorPayload:
    def test_to_response_shape(self):
        err = BudgetExceededError(
            reason="llm_call_limit_exceeded: 20 >= 20",
            workflow_id="wf-shape",
            current_usage={"total_tokens": 5000, "estimated_cost_usd": 0.5, "llm_calls": 20},
        )
        payload = err.to_response()
        assert payload["error"] == "budget_exceeded"
        assert payload["workflow_id"] == "wf-shape"
        assert "current_usage" in payload
        assert payload["current_usage"]["llm_calls"] == 20
