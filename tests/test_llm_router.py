import asyncio
from types import SimpleNamespace

import shared.llm as llm_module
from shared.llm import DEFAULT_EASY_CLOUD_MODEL, LLMRouter


class FakeMetrics:
    def __init__(self):
        self.calls = []

    async def record_llm_call(self, **kwargs):
        self.calls.append(kwargs)
        return True


def make_settings(**overrides):
    values = {
        "anthropic_api_key": "anthropic-key",
        "default_model": "gpt-4o",
        "fallback_model": "claude-sonnet-4-5",
        "ollama_base_url": "http://ollama:11434",
        "ollama_enabled": False,
        "ollama_model": "local-model",
        "ollama_task_types": ["classification", "summarize", "parsing"],
        "openai_api_key": "openai-key",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def make_router(**settings_overrides):
    router = LLMRouter.__new__(LLMRouter)
    router.settings = make_settings(**settings_overrides)
    router.metrics = FakeMetrics()
    router.usage_log = []
    return router


def make_response(content="ok"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
    )


def test_easy_tasks_prefer_ollama_when_enabled():
    router = make_router(ollama_enabled=True)

    assert router.get_model_for_task("sentiment") == "ollama/local-model"
    assert router.get_model_for_task(" translation ") == "ollama/local-model"


def test_easy_cloud_model_is_configurable_and_defaults_to_mini(monkeypatch):
    monkeypatch.delenv("EASY_TASK_MODEL", raising=False)

    assert (
        make_router().get_model_for_task("classification") == DEFAULT_EASY_CLOUD_MODEL
    )
    assert (
        make_router(easy_task_model="configured-cheap-model").get_model_for_task(
            "summarize"
        )
        == "configured-cheap-model"
    )

    monkeypatch.setenv("EASY_TASK_MODEL", "env-cheap-model")
    assert make_router().get_model_for_task("parsing") == "env-cheap-model"


def test_hard_planning_and_rca_tasks_keep_strong_models():
    router = make_router(
        ollama_enabled=True,
        ollama_task_types=["analysis", "planning", "rca"],
    )

    assert router.get_model_for_task("analysis") == "gpt-4o"
    assert router.get_model_for_task("planning") == "gpt-4o"
    assert router.get_model_for_task("rca") == "gpt-4o"
    assert router.get_model_for_task("root_cause_analysis") == "gpt-4o"


def test_custom_ollama_task_and_unknown_cloud_task_remain_supported():
    router = make_router(
        default_model="strong-default",
        ollama_enabled=True,
        ollama_task_types=["custom_lightweight"],
    )

    assert router.get_model_for_task("custom_lightweight") == "ollama/local-model"
    assert router.get_model_for_task("unknown") == "strong-default"


def test_chat_selects_task_model_without_network(monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return make_response()

    monkeypatch.setattr(llm_module.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(llm_module.litellm, "completion_cost", lambda **kwargs: 0.25)
    router = make_router(easy_task_model="configured-cheap-model")

    result = asyncio.run(
        router.chat([{"role": "user", "content": "classify"}], task="classification")
    )

    assert result == "ok"
    assert calls[0]["model"] == "configured-cheap-model"
    assert router.metrics.calls == [
        {
            "model_name": "configured-cheap-model",
            "input_tokens": 3,
            "output_tokens": 2,
            "cost_usd": 0.25,
        }
    ]


def test_chat_force_model_override_and_fallback_remain_supported(monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("provider unavailable")
        return make_response("fallback")

    monkeypatch.setattr(llm_module.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(llm_module.litellm, "completion_cost", lambda **kwargs: 0)
    router = make_router()

    result = asyncio.run(
        router.chat(
            [{"role": "user", "content": "classify"}],
            task="classification",
            force_model="explicit-model",
        )
    )

    assert result == "fallback"
    assert [call["model"] for call in calls] == ["explicit-model", "claude-sonnet-4-5"]
    assert calls[1]["api_key"] == "anthropic-key"
