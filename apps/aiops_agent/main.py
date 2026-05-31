import logging
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.llm import get_llm_router

app = FastAPI(title="AIOps Agent")
logger = logging.getLogger(__name__)
settings = get_settings()
llm_router = get_llm_router()


class TaskRequest(BaseModel):
    instruction: str
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)


@app.post("/execute")
async def execute_task(req: TaskRequest):
    """Collect basic infrastructure metrics and ask the LLM to identify anomalies."""
    logger.info("AIOps Agent received task: %s", req.instruction)
    tool_url = settings.tool_service_url.rstrip("/")
    metrics_data: Dict[str, Any] = {}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            cpu_res = await client.get(
                f"{tool_url}/prometheus/query",
                params={"query": "container_cpu_usage_seconds_total{pod=~'.*'}"},
            )
            if cpu_res.status_code == 200:
                metrics_data["cpu"] = cpu_res.json()

            memory_res = await client.get(
                f"{tool_url}/prometheus/query",
                params={"query": "container_memory_working_set_bytes{pod=~'.*'}"},
            )
            if memory_res.status_code == 200:
                metrics_data["memory"] = memory_res.json()

        analysis_prompt = f"""You are an AIOps anomaly detector. Analyze these metrics and identify anomalies.
Instruction: {req.instruction}
Metrics Data: {metrics_data}

Return a list of anomalies found. Format each as a string. If none, return an empty list.
"""
        analysis = await llm_router.chat(
            [{"role": "user", "content": analysis_prompt}],
            task="analysis",
        )
        anomalies = [line for line in analysis.splitlines() if line.strip()]
        return {
            "success": True,
            "message": "Metrics analysis completed.",
            "data": {
                "metrics": metrics_data,
                "analysis": analysis,
                "anomalies_detected": anomalies,
            },
        }
    except Exception as exc:
        logger.error("AIOps execution failed: %s", exc)
        return {"success": False, "error": str(exc)}


@app.get("/health")
async def health():
    return {"status": "ok"}
