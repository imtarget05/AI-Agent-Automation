"""Optional AgentScope 2.0 remote-agent adapter."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.internal_auth import add_internal_auth_middleware

try:
    from agentscope.agent import Agent
    from agentscope.credential import AnthropicCredential, OpenAICredential
    from agentscope.message import UserMsg
    from agentscope.model import AnthropicChatModel, OpenAIChatModel

    AGENTSCOPE_AVAILABLE = True
    AGENTSCOPE_IMPORT_ERROR = None
except ImportError as exc:  # pragma: no cover - depends on optional package
    AGENTSCOPE_AVAILABLE = False
    AGENTSCOPE_IMPORT_ERROR = str(exc)

app = FastAPI(title="AgentScope 2.0 Agent Service")
add_internal_auth_middleware(app)
logger = logging.getLogger(__name__)
settings = get_settings()


class DetailHTTPException(HTTPException):
    """HTTPException variant whose string form includes detail for direct tests."""

    def __str__(self) -> str:
        return str(self.detail)


class TaskRequest(BaseModel):
    """Task accepted from the Gateway remote-agent boundary."""

    instruction: str
    context: Optional[dict[str, Any]] = Field(default_factory=dict)


def _build_prompt(request: TaskRequest) -> str:
    """Attach structured upstream context without losing the original task."""
    if not request.context:
        return request.instruction
    return (
        f"{request.instruction}\n\n"
        "Use this upstream context as supporting data:\n"
        f"{json.dumps(request.context, ensure_ascii=False, default=str)}"
    )


def _build_agent() -> "Agent":
    """Build a stateless AgentScope 2.0 agent for one remote invocation."""
    model_name = settings.default_model
    if "claude" in model_name.lower():
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for Claude models")
        model = AnthropicChatModel(
            credential=AnthropicCredential(api_key=settings.anthropic_api_key),
            model=model_name,
            stream=False,
        )
    else:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI models")
        model = OpenAIChatModel(
            credential=OpenAICredential(api_key=settings.openai_api_key),
            model=model_name,
            stream=False,
        )

    return Agent(
        name="Assistant",
        system_prompt=(
            "Solve the assigned task precisely. Use only the supplied context "
            "and model reasoning; no tools are available in this adapter."
        ),
        model=model,
    )


@app.post("/execute")
async def execute_task(request: TaskRequest) -> dict[str, Any]:
    """Execute one stateless task with AgentScope 2.0."""
    if not settings.agentscope_enabled:
        raise DetailHTTPException(
            status_code=503,
            detail="AgentScope integration is disabled",
        )
    if not AGENTSCOPE_AVAILABLE:
        raise HTTPException(
            status_code=503,
            detail=f"AgentScope runtime unavailable: {AGENTSCOPE_IMPORT_ERROR}",
        )

    logger.info("AgentScope received task: %s", request.instruction)
    try:
        response = await _build_agent().reply(
            UserMsg("user", _build_prompt(request)),
        )
        return {
            "success": True,
            "message": "AgentScope task completed.",
            "instruction": request.instruction,
            "data": {
                "result": response.get_text_content()
                or response.model_dump(mode="json"),
            },
        }
    except Exception as exc:
        logger.error("AgentScope execution failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
async def health() -> dict[str, Any]:
    """Expose whether the opt-in adapter can serve requests."""
    ready = settings.agentscope_enabled and AGENTSCOPE_AVAILABLE
    return {
        "status": "ok" if ready else "degraded",
        "enabled": settings.agentscope_enabled,
        "agentscope_available": AGENTSCOPE_AVAILABLE,
    }
