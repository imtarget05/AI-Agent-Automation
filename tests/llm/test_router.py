"""
tests/llm/test_router.py — LLM Router tests
============================================
Tests model selection and budget integration for LLMRouter.
No real API calls are made.
"""

from __future__ import annotations

import pytest

from tests.fakes.fake_llm import FakeLLMRouter, FakeRateLimitError


class TestFakeLLMRouter:
    """FakeLLMRouter must behave like a real router for test purposes."""

    @pytest.mark.asyncio
    async def test_chat_returns_response(self):
        router = FakeLLMRouter(chat_responses=["Fake answer"])
        result = await router.chat([{"role": "user", "content": "hello"}])
        assert result == "Fake answer"

    @pytest.mark.asyncio
    async def test_chat_cycles_through_responses(self):
        router = FakeLLMRouter(chat_responses=["First", "Second", "Third"])
        r1 = await router.chat([{"role": "user", "content": "q1"}])
        r2 = await router.chat([{"role": "user", "content": "q2"}])
        r3 = await router.chat([{"role": "user", "content": "q3"}])
        assert r1 == "First"
        assert r2 == "Second"
        assert r3 == "Third"

    @pytest.mark.asyncio
    async def test_chat_repeats_last_response(self):
        router = FakeLLMRouter(chat_responses=["Only one"])
        r1 = await router.chat([{"role": "user", "content": "q1"}])
        r2 = await router.chat([{"role": "user", "content": "q2"}])
        assert r1 == r2 == "Only one"

    @pytest.mark.asyncio
    async def test_fail_on_specific_call(self):
        router = FakeLLMRouter(
            chat_responses=["ok"],
            fail_on_chat_call=0,
            chat_error=FakeRateLimitError("429"),
        )
        with pytest.raises(FakeRateLimitError):
            await router.chat([{"role": "user", "content": "q"}])

    @pytest.mark.asyncio
    async def test_succeeds_after_failed_call(self):
        router = FakeLLMRouter(
            chat_responses=["ignored", "success after failure"],
            fail_on_chat_call=0,
            chat_error=FakeRateLimitError("429"),
        )
        with pytest.raises(FakeRateLimitError):
            await router.chat([{"role": "user", "content": "q1"}])

        result = await router.chat([{"role": "user", "content": "q2"}])
        assert result == "success after failure"

    @pytest.mark.asyncio
    async def test_embed_returns_vector(self):
        router = FakeLLMRouter(embed_responses=[[0.1, 0.2, 0.3]])
        vec = await router.embed("test text")
        assert vec == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_call_count_increments(self):
        router = FakeLLMRouter(chat_responses=["ok"])
        assert router.call_count == 0
        await router.chat([{"role": "user", "content": "hi"}])
        assert router.call_count == 1

    @pytest.mark.asyncio
    async def test_reset_clears_count(self):
        router = FakeLLMRouter(chat_responses=["ok"])
        await router.chat([{"role": "user", "content": "hi"}])
        assert router.call_count == 1
        router.reset()
        assert router.call_count == 0


class TestLLMRouterModelSelection:
    """LLM Router task→model mapping (tested against the real TASK_MODEL_MAP)."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_litellm(self):
        pytest.importorskip("litellm", reason="litellm not installed in test env")

    def test_easy_task_maps_to_mini_model(self):
        from shared.llm import TASK_MODEL_MAP
        assert TASK_MODEL_MAP.get("easy") == "gpt-4o-mini"

    def test_rca_task_maps_to_strong_model(self):
        from shared.llm import TASK_MODEL_MAP
        assert TASK_MODEL_MAP.get("rca") == "gpt-4o"

    def test_computer_use_maps_to_claude(self):
        from shared.llm import TASK_MODEL_MAP
        assert "claude" in TASK_MODEL_MAP.get("computer_use", "").lower()

    def test_task_complexity_map_easy(self):
        from shared.llm import TASK_COMPLEXITY_MAP
        assert TASK_COMPLEXITY_MAP.get("summarize") == "easy"

    def test_task_complexity_map_hard(self):
        from shared.llm import TASK_COMPLEXITY_MAP
        assert TASK_COMPLEXITY_MAP.get("rca") == "hard"
