"""
LLM Router - route tasks to appropriate models with cost optimization
=====================================================================
Production hardening:
  - Exponential backoff with jitter (tenacity) for transient failures
  - Circuit-breaker pattern: after N consecutive failures, skip to fallback
  - Rate-limit detection: auto-fallback on 429/overloaded errors
  - Cost tracking via monitoring metrics
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import litellm
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    before_sleep_log,
)

from shared.config import get_settings
from shared.cost.token_budget import BudgetExceededError, get_tracker
from shared.metrics_client import get_collector
from shared.observability.logging import get_log_context, get_logger
from shared.observability.tracing import start_span

settings = get_settings()
logger = get_logger(__name__)


@dataclass(frozen=True)
class LLMCallResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

# Configure litellm
litellm.set_verbose = settings.debug
litellm.telemetry = False  # Disable telemetry in production

# ──── Task-based model routing (cost optimization) ────
DEFAULT_EASY_CLOUD_MODEL = "gpt-4o-mini"

TASK_COMPLEXITY_MAP = {
    # Lightweight transformations and classifiers
    "easy": "easy",
    "classification": "easy",
    "extract": "easy",
    "extraction": "easy",
    "parsing": "easy",
    "sentiment": "easy",
    "summarize": "easy",
    "summarization": "easy",
    "tagging": "easy",
    "translation": "easy",
    # Multi-step reasoning and operational decisions
    "hard": "hard",
    "analysis": "hard",
    "code": "hard",
    "computer_use": "hard",
    "planning": "hard",
    "rca": "hard",
    "research": "hard",
    "root_cause_analysis": "hard",
    "vision": "hard",
}

TASK_MODEL_MAP = {
    # Cheap models for simple tasks
    "easy": DEFAULT_EASY_CLOUD_MODEL,
    "classification": DEFAULT_EASY_CLOUD_MODEL,
    "extract": DEFAULT_EASY_CLOUD_MODEL,
    "extraction": DEFAULT_EASY_CLOUD_MODEL,
    "parsing": DEFAULT_EASY_CLOUD_MODEL,
    "sentiment": DEFAULT_EASY_CLOUD_MODEL,
    "summarize": DEFAULT_EASY_CLOUD_MODEL,
    "summarization": DEFAULT_EASY_CLOUD_MODEL,
    "tagging": DEFAULT_EASY_CLOUD_MODEL,
    "translation": DEFAULT_EASY_CLOUD_MODEL,
    "draft": DEFAULT_EASY_CLOUD_MODEL,
    "report_draft": DEFAULT_EASY_CLOUD_MODEL,
    # Strong models for reasoning
    "hard": "gpt-4o",
    "research": "gpt-4o",
    "code": "gpt-4o",
    "analysis": "gpt-4o",
    "planning": "gpt-4o",
    "rca": "gpt-4o",
    "root_cause_analysis": "gpt-4o",
    # Specialized models
    "computer_use": "claude-sonnet-4-5",
    "vision": "gpt-4-vision",
}

# ──── Transient error detection ────────────────────────────────────────────

_TRANSIENT_KEYWORDS = frozenset(
    {
        "overloaded",
        "rate_limit",
        "rate limit",
        "too many requests",
        "timeout",
        "connection",
        "503",
        "502",
        "429",
        "capacity",
        "server_error",
        "internal_error",
    }
)


def _is_transient(exc: Exception) -> bool:
    """Return True if the exception looks retryable (rate-limit, timeout, 5xx)."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _TRANSIENT_KEYWORDS)


def _sandbox_demo_response(messages: list[dict]) -> str:
    """Return a clearly labeled local-only demo response."""
    query = messages[-1].get("content", "").lower() if messages else ""

    # If the system prompt is present and asks for JSON (supervisor/planning)
    is_planning = any(
        "valid json" in str(m.get("content", "")).lower() for m in messages
    )

    if is_planning:
        return """{
  "analysis": "I will analyze the payment-api incident by checking metrics and root causes.",
  "action": "SYNTHESIZE",
  "tasks": [],
  "final_answer": "[SANDBOX DEMO] Incident analysis suggests a transient spike in CPU usage. All sub-services are currently healthy."
}"""

    if "runbook" in query or "cpu" in query:
        return """[SANDBOX DEMO RESPONSE]
High CPU incident example:
- Service: `payment-service`
- Example root cause: excessive garbage collection caused by a memory leak.
- Example next step: review the runbook and request operator approval before restarting a pod."""
    if "hello" in query or "hi" in query:
        return "[SANDBOX DEMO RESPONSE] Gateway demo mode is active."
    return f"[SANDBOX DEMO RESPONSE] Received query: {query}"


class _TransientLLMError(Exception):
    """Wrapper so tenacity can match on type instead of inspecting the message."""

    pass


# ──── Circuit-breaker state ────────────────────────────────────────────────


class _CircuitBreaker:
    """
    Minimal circuit-breaker for a single model.

    States:
      CLOSED  → normal operation (calls go through)
      OPEN    → model is unhealthy, calls skip straight to fallback
      HALF    → one test call allowed; success → CLOSED, failure → OPEN

    Thresholds are intentionally conservative for LLM APIs.
    """

    FAILURE_THRESHOLD = 3  # consecutive failures → open
    RECOVERY_TIMEOUT = 60.0  # seconds before attempting half-open

    def __init__(self):
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def record_success(self, model: str) -> None:
        self._failures.pop(model, None)
        self._opened_at.pop(model, None)

    def record_failure(self, model: str) -> None:
        count = self._failures.get(model, 0) + 1
        self._failures[model] = count
        if count >= self.FAILURE_THRESHOLD:
            self._opened_at[model] = time.monotonic()
            logger.warning(
                "[CircuitBreaker] OPEN for model=%s after %d failures", model, count
            )

    def is_open(self, model: str) -> bool:
        opened = self._opened_at.get(model)
        if opened is None:
            return False
        elapsed = time.monotonic() - opened
        if elapsed > self.RECOVERY_TIMEOUT:
            # Half-open: let one request through
            del self._opened_at[model]
            self._failures[model] = self.FAILURE_THRESHOLD - 1
            logger.info("[CircuitBreaker] HALF-OPEN for model=%s — testing", model)
            return False
        return True


_breaker = _CircuitBreaker()


class LLMRouter:
    """Smart LLM router with auto-fallback, retries, and cost tracking"""

    def __init__(self):
        self.settings = get_settings()
        self.metrics = get_collector(self.settings.monitoring_service_url)
        self.usage_log = []

    def get_model_for_task(self, task: str) -> str:
        """Get appropriate model for task"""
        task_key = task.strip().lower()
        complexity = TASK_COMPLEXITY_MAP.get(task_key)

        if complexity == "easy":
            if self.settings.ollama_enabled:
                return f"ollama/{self.settings.ollama_model}"
            return self._get_easy_cloud_model()

        if complexity == "hard":
            if getattr(self.settings, "reasoning_model", ""):
                return self.settings.reasoning_model
            return TASK_MODEL_MAP.get(task_key, self.settings.default_model)

        # Keep support for deployments with custom lightweight Ollama tasks.
        if self.settings.ollama_enabled:
            ollama_tasks = {t.strip().lower() for t in self.settings.ollama_task_types}
            if task_key in ollama_tasks:
                return f"ollama/{self.settings.ollama_model}"

        return TASK_MODEL_MAP.get(task_key, self.settings.default_model)

    def _get_easy_cloud_model(self) -> str:
        """Get the configured cheap cloud model for lightweight tasks."""
        return (
            getattr(self.settings, "easy_task_model", "")
            or os.getenv("EASY_TASK_MODEL", "")
            or DEFAULT_EASY_CLOUD_MODEL
        )

    async def chat(
        self,
        messages: list[dict],
        task: str = "research",
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        force_model: Optional[str] = None,
        workflow_id: str = "",
        request_id: str = "",
        session_id: str = "",
        tenant_id: str = "",
        user_id: str = "",
        agent_name: str = "",
        estimated_tokens: int = 0,
        **kwargs,
    ) -> str:
        """
        Main chat method with retry, circuit-breaker, and auto-fallback.

        Retry policy (tenacity):
          - Up to 3 attempts with exponential backoff (1s → 2s → 4s) + jitter
          - Only retries transient errors (rate-limit, timeout, 5xx)

        Circuit-breaker:
          - After 3 consecutive failures on a model, skip to fallback for 60s

        Args:
            messages: Conversation history
            task: Task type for model selection
            temperature: Sampling temperature
            max_tokens: Max tokens in response
            force_model: Explicit model override for backwards compatibility
            **kwargs: Additional LiteLLM parameters

        Returns:
            Response content string
        """
        model = force_model or self.get_model_for_task(task)
        log_context = get_log_context()
        request_id = request_id or log_context.get("request_id", "")
        tenant_id = tenant_id or log_context.get("tenant_id", "")
        user_id = user_id or log_context.get("user_id", "")
        session_id = session_id or log_context.get("session_id", "")
        agent_name = agent_name or log_context.get("agent_name", "") or task
        tracker = get_tracker(workflow_id) if workflow_id else None
        if tracker is not None:
            tracker.check_before_call(estimated_tokens=estimated_tokens)
        started_at = time.perf_counter()

        # Circuit-breaker: if primary model is tripped, go straight to fallback
        if _breaker.is_open(model) and model != self.settings.fallback_model:
            logger.info(
                "[LLM] Circuit open for %s — routing to fallback %s",
                model,
                self.settings.fallback_model,
            )
            return await self.chat(
                messages=messages,
                task=task,
                temperature=temperature,
                max_tokens=max_tokens,
                force_model=self.settings.fallback_model,
                workflow_id=workflow_id,
                request_id=request_id,
                session_id=session_id,
                tenant_id=tenant_id,
                user_id=user_id,
                agent_name=agent_name,
                estimated_tokens=estimated_tokens,
                **kwargs,
            )

        try:
            with start_span(
                "llm.call",
                {
                    "workflow_id": workflow_id,
                    "request_id": request_id,
                    "session_id": session_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "agent_name": agent_name,
                    "model": model,
                    "provider": self._provider_name(model),
                    "task": task,
                },
            ) as span:
                result = await self._call_with_retry(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                span.set_attribute("status", "success")
                span.set_attribute("prompt_tokens", result.prompt_tokens)
                span.set_attribute("completion_tokens", result.completion_tokens)
                span.set_attribute(
                    "latency_ms",
                    round((time.perf_counter() - started_at) * 1000, 2),
                )
            _breaker.record_success(model)
            if tracker is not None:
                total_tokens = result.prompt_tokens + result.completion_tokens
                tracker.check_request_tokens(total_tokens)
                tracker.record_call(
                    request_id=request_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_name=agent_name,
                    provider=self._provider_name(model),
                    model=model,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    success=True,
                )
            return result.content

        except BudgetExceededError:
            raise
        except Exception as e:
            _breaker.record_failure(model)

            # Auto-fallback on any error if not already using fallback
            if model != self.settings.fallback_model:
                logger.warning(
                    "[LLM] %s failed (%s), falling back to %s",
                    model,
                    e,
                    self.settings.fallback_model,
                )
                return await self.chat(
                    messages=messages,
                    task=task,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    force_model=self.settings.fallback_model,
                    workflow_id=workflow_id,
                    request_id=request_id,
                    session_id=session_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_name=agent_name,
                    estimated_tokens=estimated_tokens,
                    **kwargs,
                )
            if tracker is not None and not isinstance(e, BudgetExceededError):
                tracker.record_call(
                    request_id=request_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    agent_name=agent_name,
                    provider=self._provider_name(model),
                    model=model,
                    prompt_tokens=0,
                    completion_tokens=0,
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    success=False,
                    error_type=type(e).__name__,
                )
            raise

    @retry(
        retry=retry_if_exception_type(_TransientLLMError),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8, jitter=2),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_with_retry(
        self,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: Optional[int],
        **kwargs,
    ) -> LLMCallResult:
        """Single LLM call wrapped with tenacity retry for transient failures."""
        try:
            provider_opts = self._get_provider_options(model)
            api_key = self._get_api_key(model)
            if api_key:
                provider_opts["api_key"] = api_key

            # Explicit local demo mode only. Real provider errors must stay visible.
            is_placeholder_key = (
                not api_key
                or "placeholder" in api_key.lower()
                or "your_" in api_key.lower()
                or api_key.startswith("your-")
                or api_key == "your_openai_api_key_here"
                or api_key == "your_anthropic_api_key_here"
            )

            if (
                getattr(self.settings, "sandbox_demo_mode", False)
                and getattr(self.settings, "env", "development").lower()
                != "production"
                and is_placeholder_key
                and not model.startswith("ollama/")
            ):
                logger.warning("[LLMRouter] Returning explicit sandbox demo response")
                try:
                    await self.metrics.record_llm_call(
                        model_name=model,
                        input_tokens=15,
                        output_tokens=45,
                        cost_usd=0.0002,
                    )
                except Exception:
                    pass
                return LLMCallResult(
                    content=_sandbox_demo_response(messages),
                    prompt_tokens=15,
                    completion_tokens=45,
                    cost_usd=0.0002,
                )

            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **provider_opts,
                **kwargs,
            )

            input_tokens = 0
            output_tokens = 0
            cost = 0.0
            # Record metrics (best-effort, never fail the call)
            try:
                usage = getattr(response, "usage", {})
                input_tokens = getattr(usage, "prompt_tokens", 0)
                output_tokens = getattr(usage, "completion_tokens", 0)
                try:
                    cost = float(litellm.completion_cost(completion_response=response))
                except Exception:
                    cost = 0.0

                await self.metrics.record_llm_call(
                    model_name=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=float(cost),
                )
            except Exception as m_err:
                logger.warning("Failed to record LLM metrics: %s", m_err)

            return LLMCallResult(
                content=response.choices[0].message.content,
                prompt_tokens=int(input_tokens or 0),
                completion_tokens=int(output_tokens or 0),
                cost_usd=float(cost or 0.0),
            )

        except Exception as e:
            if _is_transient(e):
                raise _TransientLLMError(str(e)) from e
            raise  # Non-transient errors propagate immediately

    async def chat_with_force_model(
        self,
        messages: list[dict],
        force_model: str,
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> str:
        """
        Force specific model (bypass routing)
        """
        return await self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            force_model=force_model,
            **kwargs,
        )

    def _get_api_key(self, model: str) -> str:
        """Get API key for model provider"""
        if model.startswith("ollama/"):
            return ""
        if model.startswith("openrouter/"):
            return self.settings.openrouter_api_key
        if "gpt" in model or "text-embedding" in model:
            return self.settings.openai_api_key
        elif "claude" in model:
            return self.settings.anthropic_api_key
        elif "gemini" in model:
            return self.settings.gemini_api_key
        return ""

    @staticmethod
    def _provider_name(model: str) -> str:
        """Return a provider label safe for logs, traces, and budget records."""
        lowered = model.lower()
        if lowered.startswith("ollama/"):
            return "ollama"
        if lowered.startswith("openrouter/"):
            return "openrouter"
        if "claude" in lowered:
            return "anthropic"
        if "gemini" in lowered:
            return "google"
        if "gpt" in lowered or "text-embedding" in lowered:
            return "openai"
        return "unknown"

    def _get_provider_options(self, model: str) -> dict:
        """Provider-specific options (e.g., api_base for Ollama)"""
        if model.startswith("ollama/"):
            return {"api_base": self.settings.ollama_base_url}
        return {}

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using OpenAI or Ollama, with sandbox fallback"""
        api_key = self.settings.openai_api_key
        is_placeholder_key = (
            not api_key
            or "placeholder" in api_key.lower()
            or "your_" in api_key.lower()
            or api_key.startswith("your-")
            or api_key == "your_openai_api_key_here"
        )

        if (
            getattr(self.settings, "sandbox_demo_mode", False)
            and getattr(self.settings, "env", "development").lower() != "production"
            and is_placeholder_key
            and self.settings.embedding_provider.lower() != "ollama"
        ):
            logger.warning("[LLMRouter] Returning dummy embedding in sandbox demo mode")
            # 1536 is standard for text-embedding-3-small
            return [0.0] * 1536

        if (
            self.settings.embedding_provider.lower() == "ollama"
            and self.settings.ollama_enabled
        ):
            response = await litellm.aembedding(
                model=f"ollama/{self.settings.ollama_embed_model}",
                input=text,
                api_base=self.settings.ollama_base_url,
            )
        else:
            response = await litellm.aembedding(
                model=self.settings.embedding_model,
                input=text,
                api_key=self.settings.openai_api_key,
            )
        return response.data[0]["embedding"]


# Global instance
_router: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get or create LLM router instance"""
    global _router
    if _router is None:
        _router = LLMRouter()
    return _router
