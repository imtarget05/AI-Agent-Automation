import json
import logging
import re
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.llm import get_llm_router

app = FastAPI(title="RCA Agent")
logger = logging.getLogger(__name__)
settings = get_settings()
llm_router = get_llm_router()


class TaskRequest(BaseModel):
    instruction: str
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)


async def _post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


@app.post("/execute")
async def execute_task(req: TaskRequest):
    """Run a bounded RCA reasoning loop with read-only evidence gathering."""
    logger.info("RCA Agent received task: %s", req.instruction)
    system_prompt = """You are a Root Cause Analysis (RCA) expert.
Gather evidence and reason step by step. Available actions:
1. RAG_SEARCH: {"action": "RAG_SEARCH", "query": "search query"}
2. AIOPS_LOOKUP: {"action": "AIOPS_LOOKUP", "instruction": "what to check"}
3. TOOL_CALL: {"action": "TOOL_CALL", "instruction": "read-only tool query"}

Always provide your THOUGHT before an ACTION. TOOL_CALL supports read-only
infrastructure evidence gathering only. When you have a supported conclusion,
provide it in a FINAL_ANSWER block.
"""
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Problem Statement: {req.instruction}\nContext from Gateway: {req.context}",
        },
    ]
    history = []

    try:
        for current_step in range(1, settings.rca_max_reasoning_steps + 1):
            logger.info("[RCA] Step %s", current_step)
            response = await llm_router.chat(messages, task="analysis")
            history.append({"step": current_step, "response": response})
            messages.append({"role": "assistant", "content": response})

            if "FINAL_ANSWER" in response:
                return {
                    "success": True,
                    "message": "RCA completed.",
                    "history": history,
                    "final_conclusion": response,
                }

            action_match = re.search(r'\{.*"action":.*\}', response, re.DOTALL)
            if not action_match:
                messages.append(
                    {
                        "role": "user",
                        "content": "Please continue your analysis or provide a FINAL_ANSWER.",
                    }
                )
                continue

            try:
                action = json.loads(action_match.group())
                action_type = action.get("action")

                if action_type == "RAG_SEARCH":
                    result = await _post_json(
                        f"{settings.rag_service_url.rstrip('/')}/retrieve",
                        {"query": action.get("query", ""), "top_k": 3},
                    )
                    observation = str(result.get("results", []))
                elif action_type == "AIOPS_LOOKUP":
                    result = await _post_json(
                        f"{settings.aiops_agent_service_url.rstrip('/')}/execute",
                        {"instruction": action.get("instruction", "")},
                    )
                    observation = str(result.get("data", result))
                elif action_type == "TOOL_CALL":
                    result = await _post_json(
                        f"{settings.tool_service_url.rstrip('/')}/execute",
                        {"instruction": action.get("instruction", "")},
                    )
                    observation = str(result)
                else:
                    observation = f"Unsupported RCA action: {action_type}"

                messages.append(
                    {"role": "user", "content": f"OBSERVATION: {observation}"}
                )
                history.append({"step": current_step, "observation": observation})
            except Exception as exc:
                logger.error("Error parsing or executing RCA action: %s", exc)
                messages.append(
                    {"role": "user", "content": f"OBSERVATION ERROR: {exc}"}
                )

        return {
            "success": False,
            "message": "RCA reasoning exhausted without a final answer.",
            "history": history,
            "final_conclusion": "Incomplete analysis.",
        }
    except Exception as exc:
        logger.error("RCA execution failed: %s", exc)
        return {"success": False, "error": str(exc)}


@app.get("/health")
async def health():
    return {"status": "ok"}
