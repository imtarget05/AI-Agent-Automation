"""
tests/fakes/fake_llm.py — Fake LLM provider for testing
=========================================================
Provides deterministic, offline LLM responses so tests never call real APIs.

Usage:
    from tests.fakes.fake_llm import FakeLLMProvider, FakeLLMRouter

    # Sequential responses
    fake = FakeLLMProvider(responses=["First answer", "Second answer"])

    # Simulate failure on a specific call index
    fake = FakeLLMProvider(responses=["ok"], fail_on_call=0, error=RateLimitError())

    # Use as drop-in for LLMRouter in tests:
    router = FakeLLMRouter(chat_responses=["result"])
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional


# ──── Exception types ─────────────────────────────────────────────────────────

class FakeLLMError(Exception):
    """Base error for simulated LLM failures."""


class FakeRateLimitError(FakeLLMError):
    """Simulates a 429 / rate-limit response."""


class FakeProviderError(FakeLLMError):
    """Simulates a 5xx server error."""


class FakeTimeoutError(FakeLLMError):
    """Simulates a network timeout."""


class FakeMalformedJSONError(FakeLLMError):
    """Simulates a response with invalid JSON when structured output expected."""


# ──── Token usage helper ──────────────────────────────────────────────────────

@dataclass
class FakeTokenUsage:
    prompt_tokens: int = 100
    completion_tokens: int = 50
    total_tokens: int = 150

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


# ──── Core fake provider ──────────────────────────────────────────────────────

class FakeLLMProvider:
    """Configurable fake that cycles through a list of canned responses.

    Parameters:
        responses     List of strings (or dicts for tool-call responses).
                      The provider cycles through them in order and repeats
                      the last one if exhausted.
        fail_on_call  If set, raises *error* on this 0-based call index.
        error         Exception instance to raise on *fail_on_call*.
        usage         Token usage to attach to each response.
        latency_ms    Simulated async delay per call (0 = instant).
    """

    def __init__(
        self,
        responses: Optional[list[Any]] = None,
        fail_on_call: Optional[int] = None,
        error: Optional[Exception] = None,
        usage: Optional[FakeTokenUsage] = None,
        latency_ms: float = 0.0,
    ) -> None:
        self._responses: list[Any] = responses or ["[FAKE LLM RESPONSE]"]
        self._fail_on_call = fail_on_call
        self._error = error or FakeProviderError("Simulated provider error")
        self._usage = usage or FakeTokenUsage()
        self._latency_ms = latency_ms
        self._call_count = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def _next_response(self) -> Any:
        idx = min(self._call_count, len(self._responses) - 1)
        return self._responses[idx]

    async def ainvoke(
        self,
        messages: list[dict],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Async chat completion — mirrors litellm / LLMRouter interface."""
        if self._latency_ms > 0:
            await asyncio.sleep(self._latency_ms / 1000)

        if (
            self._fail_on_call is not None
            and self._call_count == self._fail_on_call
        ):
            self._call_count += 1
            raise self._error

        response = self._next_response()
        self._call_count += 1

        return {
            "content": response if isinstance(response, str) else str(response),
            "usage": self._usage.to_dict(),
            "model": kwargs.get("model", "fake-model"),
            "provider": "fake",
        }

    def invoke(self, messages: list[dict], **kwargs: Any) -> dict[str, Any]:
        """Synchronous wrapper (runs ainvoke in event loop)."""
        return asyncio.get_event_loop().run_until_complete(
            self.ainvoke(messages, **kwargs)
        )

    def reset(self) -> None:
        """Reset call counter for reuse within the same test session."""
        self._call_count = 0


# ──── FakeLLMRouter — drop-in for shared.llm.LLMRouter ──────────────────────

class FakeLLMRouter:
    """Thin wrapper around FakeLLMProvider that mirrors the LLMRouter API.

    Parameters:
        chat_responses    Responses returned by .chat()
        embed_responses   Responses returned by .embed() (default: [0.1]*10)
        fail_on_chat_call Fail on this 0-based chat call index
        chat_error        Error to raise on failure
        usage             Token usage per call
    """

    def __init__(
        self,
        chat_responses: Optional[list[str]] = None,
        embed_responses: Optional[list[list[float]]] = None,
        fail_on_chat_call: Optional[int] = None,
        chat_error: Optional[Exception] = None,
        usage: Optional[FakeTokenUsage] = None,
        latency_ms: float = 0.0,
    ) -> None:
        self._provider = FakeLLMProvider(
            responses=chat_responses or ["[FAKE RESPONSE]"],
            fail_on_call=fail_on_chat_call,
            error=chat_error,
            usage=usage,
            latency_ms=latency_ms,
        )
        self._embed_responses = embed_responses or [[0.1] * 10]
        self._embed_call_count = 0

    @property
    def call_count(self) -> int:
        return self._provider.call_count

    async def chat(
        self,
        messages: list[dict],
        task: str = "hard",
        **kwargs: Any,
    ) -> str:
        result = await self._provider.ainvoke(messages, **kwargs)
        return result["content"]

    async def embed(self, text: str) -> list[float]:
        idx = min(self._embed_call_count, len(self._embed_responses) - 1)
        self._embed_call_count += 1
        return self._embed_responses[idx]

    def get_model_for_task(self, task: str) -> str:  # noqa: ARG002
        return "fake-model"

    def reset(self) -> None:
        self._provider.reset()
        self._embed_call_count = 0


# ──── Scenario builders ───────────────────────────────────────────────────────

def make_rca_router(
    *,
    steps: int = 2,
    final_answer: str = "Root cause: high CPU from GC pressure.",
) -> FakeLLMRouter:
    """Return a FakeLLMRouter that mimics a successful RCA reasoning loop."""
    step_responses = [
        f'{{"action": "RAG_SEARCH", "query": "cpu high step {i}"}}'
        for i in range(1, steps)
    ]
    step_responses.append(
        f"THOUGHT: enough evidence.\nFINAL_ANSWER: {final_answer}"
    )
    return FakeLLMRouter(chat_responses=step_responses)


def make_fallback_router(
    *,
    primary_error: Optional[Exception] = None,
    fallback_response: str = "Fallback answer",
) -> FakeLLMRouter:
    """First call raises an error; second call returns the fallback response."""
    err = primary_error or FakeRateLimitError("rate limit hit")
    return FakeLLMRouter(
        chat_responses=["ignored", fallback_response],
        fail_on_chat_call=0,
        chat_error=err,
    )


def make_budget_exhausting_router(
    *,
    tokens_per_call: int = 10_000,
    max_calls: int = 10,
) -> FakeLLMRouter:
    """Returns large token counts to exhaust budget quickly in tests."""
    usage = FakeTokenUsage(
        prompt_tokens=tokens_per_call // 2,
        completion_tokens=tokens_per_call // 2,
        total_tokens=tokens_per_call,
    )
    return FakeLLMRouter(
        chat_responses=["[LARGE RESPONSE]"] * max_calls,
        usage=usage,
    )
