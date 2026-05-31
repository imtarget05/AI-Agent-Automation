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
from shared.metrics_client import get_collector

settings = get_settings()
logger = logging.getLogger(__name__)

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
                **kwargs,
            )

        try:
            content = await self._call_with_retry(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            _breaker.record_success(model)
            return content

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
                    **kwargs,
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
    ) -> str:
        """Single LLM call wrapped with tenacity retry for transient failures."""
        try:
            provider_opts = self._get_provider_options(model)
            api_key = self._get_api_key(model)
            if api_key:
                provider_opts["api_key"] = api_key

            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **provider_opts,
                **kwargs,
            )

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

            return response.choices[0].message.content

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
        if "gpt" in model or "text-embedding" in model:
            return self.settings.openai_api_key
        elif "claude" in model:
            return self.settings.anthropic_api_key
        return ""

    def _get_provider_options(self, model: str) -> dict:
        """Provider-specific options (e.g., api_base for Ollama)"""
        if model.startswith("ollama/"):
            return {"api_base": self.settings.ollama_base_url}
        return {}

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using OpenAI"""
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
