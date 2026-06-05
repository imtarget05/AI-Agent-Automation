import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.agentscope_agent import main


def test_agentscope_execute_fails_closed_when_disabled(monkeypatch):
    monkeypatch.setattr(main, "settings", SimpleNamespace(agentscope_enabled=False))

    with pytest.raises(HTTPException, match="disabled") as exc_info:
        asyncio.run(main.execute_task(main.TaskRequest(instruction="research issue")))

    assert exc_info.value.status_code == 503


def test_agentscope_prompt_preserves_structured_context():
    prompt = main._build_prompt(
        main.TaskRequest(
            instruction="Explain the incident",
            context={"service": "payments", "latency_ms": 4200},
        )
    )

    assert "Explain the incident" in prompt
    assert '"service": "payments"' in prompt
    assert '"latency_ms": 4200' in prompt
