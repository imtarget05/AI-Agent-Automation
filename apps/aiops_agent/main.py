from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.llm import get_llm_router
from shared.internal_auth import add_internal_auth_middleware
from shared.internal_auth import get_internal_service_headers
from shared.observability.logging import get_logger
from shared.observability.tracing import start_span

app = FastAPI(title="AIOps Agent")
add_internal_auth_middleware(app)
logger = get_logger(__name__)
settings = get_settings()
llm_router = get_llm_router()


class TaskRequest(BaseModel):
    instruction: str
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)


@app.post("/execute")
async def execute_task(req: TaskRequest):
    """Analyze metrics or logs and identify anomalies or summarize findings."""
    logger.info("AIOps Agent received task: %s", req.instruction)
    context = req.context or {}
    workflow_id = str(context.get("workflow_id", ""))
    session_id = str(context.get("session_id", ""))
    tool_url = settings.tool_service_url.rstrip("/")
    instruction_lower = req.instruction.lower()

    # Determine task type for cost-optimized routing
    task_type = "analysis"  # Default to hard reasoning
    if any(kw in instruction_lower for kw in ("summarize", "summary", "log summary")):
        task_type = "summarize"
    elif any(kw in instruction_lower for kw in ("classify", "classification", "category")):
        task_type = "classification"

    metrics_data: Dict[str, Any] = {}

    try:
        # If it's a log-related task, try to fetch logs
        if "log" in instruction_lower:
            pod_name = context.get("pod_name") or context.get("pod")
            if pod_name:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    headers = get_internal_service_headers()
                    namespace = context.get("namespace", "default")
                    log_res = await client.get(
                        f"{tool_url}/k8s/logs",
                        params={"pod_name": pod_name, "namespace": namespace, "tail_lines": 100},
                        headers=headers,
                    )
                    if log_res.status_code == 200:
                        metrics_data["logs"] = log_res.json().get("logs", "")

        # Otherwise fetch standard metrics
        if not metrics_data.get("logs") or "metric" in instruction_lower:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = get_internal_service_headers()
                cpu_res = await client.get(
                    f"{tool_url}/prometheus/query",
                    params={"query": "container_cpu_usage_seconds_total{pod=~'.*'}"},
                    headers=headers,
                )
                if cpu_res.status_code == 200:
                    metrics_data["cpu"] = cpu_res.json()

                memory_res = await client.get(
                    f"{tool_url}/prometheus/query",
                    params={"query": "container_memory_working_set_bytes{pod=~'.*'}"},
                    headers=headers,
                )
                if memory_res.status_code == 200:
                    metrics_data["memory"] = memory_res.json()

        analysis_prompt = f"""You are an AIOps specialist. Analyze the following data based on the instruction.
Instruction: {req.instruction}
Data: {metrics_data}

Provide a clear and concise response.
"""
        with start_span(
            "aiops.execution",
            {
                "workflow_id": workflow_id,
                "session_id": session_id,
                "agent_name": "aiops_agent",
                "task_type": task_type,
            },
        ):
            analysis = await llm_router.chat(
                [{"role": "user", "content": analysis_prompt}],
                task=task_type,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_name="aiops_agent",
                estimated_tokens=1500,
            )
        
        return {
            "success": True,
            "message": f"AIOps {task_type} completed.",
            "data": {
                "input_data": metrics_data,
                "analysis": analysis,
                "task_type": task_type,
            },
        }
    except Exception as exc:
        logger.error("AIOps execution failed: %s", exc)
        return {"success": False, "error": str(exc)}


@app.get("/health")
async def health():
    return {"status": "ok"}
