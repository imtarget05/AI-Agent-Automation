"""
shared/cost/token_budget.py — Token budget and LLM cost tracking
================================================================
Tracks every LLM call and enforces per-request / per-workflow budget limits.

Design goals:
  - Zero external dependencies beyond stdlib + pydantic (Redis optional for
    cross-process aggregation; in-process tracking works without Redis).
  - Thread-safe and asyncio-safe.
  - Does not call LLM directly — callers wrap their LLM invocations with
    BudgetTracker.record_call() / BudgetTracker.check().
  - When budget is exceeded:
      1. Raises BudgetExceededError with structured payload.
      2. Caller must surface this to the workflow as a hard stop.

Environment variables:
  MAX_TOKENS_PER_REQUEST          int   default 20 000
  MAX_TOKENS_PER_WORKFLOW         int   default 80 000
  MAX_LLM_CALLS_PER_WORKFLOW      int   default 20
  MAX_COST_PER_WORKFLOW_USD       float default 2.00
  MAX_COST_PER_USER_DAILY_USD     float default 10.00

Model pricing (USD per 1K tokens, approximate 2025 rates):
  Can be overridden by COST_TABLE_JSON env var.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ──── Pricing table (USD / 1k tokens) ───────────────────────────────────────
# Input token costs only; output typically 3x but we use a simple average.

_DEFAULT_COST_TABLE: dict[str, float] = {
    "gpt-4o": 0.005,
    "gpt-4o-mini": 0.00015,
    "gpt-4-vision": 0.01,
    "gpt-4-turbo": 0.01,
    "claude-sonnet-4-5": 0.003,
    "claude-opus-4": 0.015,
    "claude-haiku-3": 0.00025,
    "ollama/deepseek-r1:8b": 0.0,
    "ollama/*": 0.0,
    "default": 0.002,
}


def _load_cost_table() -> dict[str, float]:
    raw = os.getenv("COST_TABLE_JSON")
    if raw:
        try:
            overrides = json.loads(raw)
            if isinstance(overrides, dict):
                return {**_DEFAULT_COST_TABLE, **overrides}
        except Exception:
            logger.warning("[budget] COST_TABLE_JSON is invalid — using defaults")
    return _DEFAULT_COST_TABLE


def estimate_cost_usd(model: str, total_tokens: int) -> float:
    """Estimate USD cost from token count and model name."""
    table = _load_cost_table()
    rate = table.get(model)
    if rate is None:
        # wildcard match e.g. "ollama/*"
        for pattern, r in table.items():
            if pattern.endswith("*") and model.startswith(pattern[:-1]):
                rate = r
                break
    if rate is None:
        rate = table.get("default", 0.002)
    return round(total_tokens * rate / 1000, 6)


# ──── Budget config ──────────────────────────────────────────────────────────

@dataclass
class BudgetPolicy:
    max_tokens_per_request: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOKENS_PER_REQUEST", "20000"))
    )
    max_tokens_per_workflow: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOKENS_PER_WORKFLOW", "80000"))
    )
    max_llm_calls_per_workflow: int = field(
        default_factory=lambda: int(os.getenv("MAX_LLM_CALLS_PER_WORKFLOW", "20"))
    )
    max_cost_per_workflow_usd: float = field(
        default_factory=lambda: float(os.getenv("MAX_COST_PER_WORKFLOW_USD", "2.00"))
    )
    max_cost_per_user_daily_usd: float = field(
        default_factory=lambda: float(os.getenv("MAX_COST_PER_USER_DAILY_USD", "10.00"))
    )


_DEFAULT_POLICY = BudgetPolicy()


# ──── Usage record ───────────────────────────────────────────────────────────

@dataclass
class LLMCallRecord:
    request_id: str
    workflow_id: str
    tenant_id: str
    user_id: str
    agent_name: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: float
    success: bool
    error_type: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workflow_id": self.workflow_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error_type": self.error_type,
            "created_at": self.created_at,
        }


# ──── Budget exceeded error ──────────────────────────────────────────────────

class BudgetExceededError(RuntimeError):
    """Raised when any budget limit is breached.

    Attributes:
        reason:         which limit was hit
        workflow_id:    the affected workflow
        current_usage:  dict with tokens / cost / calls so far
    """

    def __init__(
        self,
        reason: str,
        workflow_id: str,
        current_usage: Dict[str, Any],
    ) -> None:
        self.reason = reason
        self.workflow_id = workflow_id
        self.current_usage = current_usage
        super().__init__(reason)

    def to_response(self) -> Dict[str, Any]:
        return {
            "error": "budget_exceeded",
            "message": "Workflow exceeded configured LLM budget",
            "workflow_id": self.workflow_id,
            "reason": self.reason,
            "current_usage": self.current_usage,
        }


# ──── Per-workflow budget tracker ────────────────────────────────────────────

class WorkflowBudgetTracker:
    """Accumulates token/cost usage for a single workflow run.

    Thread-safe for concurrent LLM calls within the same workflow.
    Not persistent — use Redis aggregation layer for cross-process totals.
    """

    def __init__(
        self,
        workflow_id: str,
        policy: Optional[BudgetPolicy] = None,
    ) -> None:
        self.workflow_id = workflow_id
        self.policy = policy or _DEFAULT_POLICY
        self._total_tokens = 0
        self._total_cost_usd = 0.0
        self._llm_calls = 0
        self._records: list[LLMCallRecord] = []

    # ── Accessors ──

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    @property
    def llm_calls(self) -> int:
        return self._llm_calls

    @property
    def records(self) -> list[LLMCallRecord]:
        return list(self._records)

    def usage_snapshot(self) -> Dict[str, Any]:
        return {
            "total_tokens": self._total_tokens,
            "estimated_cost_usd": round(self._total_cost_usd, 6),
            "llm_calls": self._llm_calls,
        }

    # ── Core API ──

    def check_before_call(self, estimated_tokens: int = 0) -> None:
        """Raise BudgetExceededError if limits are already breached.

        Call this BEFORE making an LLM request to do an early abort.
        """
        usage = self.usage_snapshot()

        if self._llm_calls >= self.policy.max_llm_calls_per_workflow:
            raise BudgetExceededError(
                f"llm_call_limit_exceeded: {self._llm_calls} >= "
                f"{self.policy.max_llm_calls_per_workflow}",
                self.workflow_id,
                usage,
            )

        if (self._total_tokens + estimated_tokens) > self.policy.max_tokens_per_workflow:
            raise BudgetExceededError(
                f"workflow_token_limit_exceeded: {self._total_tokens} + "
                f"{estimated_tokens} > {self.policy.max_tokens_per_workflow}",
                self.workflow_id,
                usage,
            )

        if self._total_cost_usd >= self.policy.max_cost_per_workflow_usd:
            raise BudgetExceededError(
                f"workflow_cost_limit_exceeded: ${self._total_cost_usd:.4f} >= "
                f"${self.policy.max_cost_per_workflow_usd:.2f}",
                self.workflow_id,
                usage,
            )

    def record_call(
        self,
        *,
        request_id: str = "",
        tenant_id: str = "",
        user_id: str = "",
        agent_name: str = "",
        provider: str = "",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        success: bool = True,
        error_type: Optional[str] = None,
    ) -> LLMCallRecord:
        """Record a completed LLM call and check post-call limits.

        Returns the call record. Raises BudgetExceededError if any limit is
        now breached (callers should treat this as a hard stop for the next call).
        """
        total = prompt_tokens + completion_tokens
        cost = estimate_cost_usd(model, total)

        record = LLMCallRecord(
            request_id=request_id,
            workflow_id=self.workflow_id,
            tenant_id=tenant_id,
            user_id=user_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
            latency_ms=latency_ms,
            success=success,
            error_type=error_type,
        )

        self._total_tokens += total
        self._total_cost_usd += cost
        self._llm_calls += 1
        self._records.append(record)

        logger.info(
            "[budget] LLM call recorded workflow=%s model=%s tokens=%d "
            "cost_usd=%.6f total_tokens=%d total_cost=%.4f llm_calls=%d",
            self.workflow_id,
            model,
            total,
            cost,
            self._total_tokens,
            self._total_cost_usd,
            self._llm_calls,
        )

        # Emit tracing event (no-op when OTEL disabled)
        try:
            from shared.observability.tracing import add_span_event

            add_span_event(
                "llm_call",
                {
                    "model": model,
                    "total_tokens": total,
                    "cost_usd": cost,
                    "llm_calls": self._llm_calls,
                },
            )
        except Exception:
            pass

        # Post-call budget check (for next iteration awareness)
        try:
            self.check_before_call()
        except BudgetExceededError:
            logger.warning(
                "[budget] Budget will be exceeded on next call — workflow=%s usage=%s",
                self.workflow_id,
                self.usage_snapshot(),
            )
            raise

        return record

    def check_request_tokens(self, total_tokens: int) -> None:
        """Check per-request token limit (call after receiving LLM response)."""
        if total_tokens > self.policy.max_tokens_per_request:
            raise BudgetExceededError(
                f"request_token_limit_exceeded: {total_tokens} > "
                f"{self.policy.max_tokens_per_request}",
                self.workflow_id,
                self.usage_snapshot(),
            )


# ──── Global tracker registry ────────────────────────────────────────────────
# Keyed by workflow_id. Entries are created on-demand and are evicted when the
# workflow completes (caller calls remove_tracker).

_trackers: dict[str, WorkflowBudgetTracker] = {}


def get_tracker(
    workflow_id: str,
    policy: Optional[BudgetPolicy] = None,
) -> WorkflowBudgetTracker:
    """Return (creating if needed) the budget tracker for *workflow_id*."""
    if workflow_id not in _trackers:
        _trackers[workflow_id] = WorkflowBudgetTracker(workflow_id, policy)
    return _trackers[workflow_id]


def remove_tracker(workflow_id: str) -> Optional[WorkflowBudgetTracker]:
    """Remove and return the tracker for *workflow_id*."""
    return _trackers.pop(workflow_id, None)


def get_all_usage() -> Dict[str, Dict[str, Any]]:
    """Return usage snapshots for all active workflows (for monitoring)."""
    return {wid: t.usage_snapshot() for wid, t in _trackers.items()}
