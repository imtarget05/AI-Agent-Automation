"""
FastAPI Gateway - Main entry point for all requests
"""

import uuid
import logging
import json
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from shared.approvals import ApprovalClient, ApprovalServiceError
from shared.config import get_settings
from shared.guardrails import GuardrailClient, GuardrailServiceError
from shared.models import ModuleType, TaskRequest, TaskResponse, TaskStatus
from shared.memory import get_long_term_memory
from apps.gateway.orchestrator import get_orchestrator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
guardrail_client = GuardrailClient()
approval_client = ApprovalClient()
SELF_HEALING_ACTIONS = {
    "restart_deployment",
    "scale_deployment",
    "delete_pod",
}
TASK_STORE_PATH = Path("data/gateway_tasks.json")
TASK_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
_task_store: dict[str, dict[str, Any]] = {}


def _load_task_store() -> None:
    """Load async task state from disk if available."""
    global _task_store
    if not TASK_STORE_PATH.exists():
        _task_store = {}
        return

    try:
        _task_store = json.loads(TASK_STORE_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to load task store: %s", exc)
        _task_store = {}


def _save_task_store() -> None:
    """Persist async task state to disk."""
    try:
        TASK_STORE_PATH.write_text(
            json.dumps(_task_store, indent=2, ensure_ascii=True), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("Failed to save task store: %s", exc)


def _serialize_task_response(result: dict[str, Any]) -> dict[str, Any]:
    """Store only JSON-safe task response data."""

    def _convert(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: _convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_convert(item) for item in value]
        if hasattr(value, "model_dump"):
            return _convert(value.model_dump(mode="json"))
        if hasattr(value, "value"):
            return value.value
        return value

    return _convert(result)


async def _notify_callback(callback_url: str, payload: dict[str, Any]) -> None:
    """Best-effort callback delivery for async task completion."""
    try:
        async with httpx.AsyncClient(
            timeout=settings.agent_http_timeout_seconds
        ) as client:
            response = await client.post(callback_url, json=payload)
            response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "Async task callback delivery failed for %s: %s", callback_url, exc
        )


# ──── Lifecycle ────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic"""
    logger.info("🚀 Starting Personal AI Agent Gateway")
    _load_task_store()
    # Initialize long-term memory collection
    try:
        await get_long_term_memory().init()
    except Exception as e:
        logger.warning(f"Long-term memory init failed: {e}")
    yield
    logger.info("🛑 Shutting down")


# ──── Create App ────

app = FastAPI(
    title="Personal AI Agent Gateway",
    description="Multi-agent orchestration platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ──── CORS Middleware ────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──── Security ────
security = HTTPBearer()


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify API key from Authorization header"""
    if credentials.credentials != get_settings().api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key"
        )
    return credentials.credentials


async def ensure_safe_input(prompt: str) -> None:
    """Reject unsafe prompts before they reach the orchestration LLM."""
    try:
        verdict = await guardrail_client.guard_input(prompt)
    except GuardrailServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not verdict.get("safe"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=verdict.get("reason", "Input rejected by guardrail service"),
        )


# ──── Health Check ────


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.app_version,
    }


# ──── Incident Analysis ────


class IncidentRequest(BaseModel):
    incident_data: dict
    session_id: Optional[str] = None


@app.post("/incident/analyze", response_model=TaskResponse)
async def analyze_incident(
    request: IncidentRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Analyze an incident using AIOps, RCA, RAG, and Tool agents.
    """
    logger.info("Received incident for analysis: %s", request.incident_data)

    # We convert the structured JSON into a natural language request for the manager
    # Or bypass manager and execute an AIOps workflow directly.
    # For now, we will construct a prompt for the manager to plan the workflow.
    user_input = f"Incident occurred: {request.incident_data}. Please analyze anomalies, find root cause, and draft an email report."

    session_id = request.session_id or str(uuid.uuid4())
    orchestrator = get_orchestrator()

    # Allowed modules for incident analysis
    allowed_modules = [
        ModuleType.AIOPS,
        ModuleType.TOOL,
        ModuleType.RAG,
        ModuleType.RCA,
        ModuleType.REPORT,
        ModuleType.EMAIL,
    ]

    start_time = datetime.utcnow()
    try:
        result = await orchestrator.execute(
            user_input=user_input,
            session_id=session_id,
            allowed_modules=allowed_modules,
        )

        exec_time = (datetime.utcnow() - start_time).total_seconds()

        return TaskResponse(
            status="completed",
            plan=result.get("plan"),
            result=result.get("final_answer"),
            error=result.get("error"),
            execution_time_seconds=exec_time,
        )
    except Exception as e:
        logger.error("Incident analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ──── Task Execution ────


@app.post("/execute", response_model=TaskResponse)
async def execute_task(
    request: TaskRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    Execute a task across available agents

    - **user_input**: Natural language instruction (e.g., "Find iPhone prices on Shopee")
    - **session_id**: Optional session ID for context (auto-generated if not provided)
    - **modules**: Optional list of modules to use (auto-detected if not provided)

    Returns execution plan, intermediate results, and final synthesized answer
    """
    session_id = request.session_id or str(uuid.uuid4())
    start_time = datetime.utcnow()
    await ensure_safe_input(request.user_input)

    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.execute(
            request.user_input,
            session_id,
            allowed_modules=request.modules,
        )

        execution_time = (datetime.utcnow() - start_time).total_seconds()

        return TaskResponse(
            status="success",
            plan=result.get("plan"),
            result=result.get("final_answer"),
            error=result.get("error"),
            execution_time_seconds=execution_time,
        )

    except Exception as e:
        logger.error(f"[GATEWAY] Task execution failed: {e}", exc_info=True)
        return TaskResponse(
            status="error",
            result=None,
            error=str(e),
            execution_time_seconds=(datetime.utcnow() - start_time).total_seconds(),
        )


# ──── Async Task Execution (background) ────


class AsyncTaskRequest(BaseModel):
    """Request for background task"""

    user_input: str
    session_id: Optional[str] = None
    callback_url: Optional[str] = None  # Webhook to call when done
    modules: Optional[list[ModuleType]] = None


@app.post("/execute-async")
async def execute_task_async(
    request: AsyncTaskRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key),
):
    """
    Execute task asynchronously (returns immediately with task ID)

    Polls /task-status/{task_id} to get results when ready
    """
    session_id = request.session_id or str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    await ensure_safe_input(request.user_input)

    _task_store[task_id] = {
        "task_id": task_id,
        "session_id": session_id,
        "status": TaskStatus.PENDING.value,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "user_input": request.user_input,
        "callback_url": request.callback_url,
        "modules": [module.value for module in request.modules]
        if request.modules
        else None,
        "result": None,
        "error": None,
    }
    _save_task_store()

    async def run_task():
        """Run in background"""
        _task_store[task_id]["status"] = TaskStatus.RUNNING.value
        _task_store[task_id]["updated_at"] = datetime.utcnow().isoformat()
        _save_task_store()

        orchestrator = get_orchestrator()
        try:
            run_result = await orchestrator.execute(
                request.user_input,
                session_id,
                allowed_modules=request.modules,
            )
            _task_store[task_id].update(
                {
                    "status": TaskStatus.COMPLETED.value,
                    "result": _serialize_task_response(run_result),
                    "error": run_result.get("error"),
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            _save_task_store()

            if request.callback_url:
                await _notify_callback(
                    request.callback_url,
                    {
                        "task_id": task_id,
                        "session_id": session_id,
                        "status": TaskStatus.COMPLETED.value,
                        "result": _serialize_task_response(run_result),
                        "error": run_result.get("error"),
                    },
                )
        except Exception as exc:
            logger.error("Async task %s failed: %s", task_id, exc, exc_info=True)
            _task_store[task_id].update(
                {
                    "status": TaskStatus.FAILED.value,
                    "error": str(exc),
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            _save_task_store()

            if request.callback_url:
                await _notify_callback(
                    request.callback_url,
                    {
                        "task_id": task_id,
                        "session_id": session_id,
                        "status": TaskStatus.FAILED.value,
                        "result": None,
                        "error": str(exc),
                    },
                )

        logger.info(f"Async task {task_id} completed")

    background_tasks.add_task(run_task)

    return {
        "task_id": task_id,
        "session_id": session_id,
        "status": "queued",
        "message": f"Task queued. Poll /task-status/{task_id} for results",
    }


@app.get("/task-status/{task_id}")
async def get_task_status(
    task_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get status of async task"""
    task = _task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


# ---- Human Approval Workflow ----


class ToolApprovalRequest(BaseModel):
    """Proposed guarded tool action requiring an operator decision."""

    tool_name: str
    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class ToolApprovalDecision(BaseModel):
    """Operator decision for a pending tool action."""

    approved: bool
    decided_by: str


class SelfHealingApprovalRequest(BaseModel):
    """Kubernetes write action proposed by the DevOps workflow."""

    action: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None


class SelfHealingApprovalDecision(BaseModel):
    """Operator identity recorded with an approval decision."""

    decided_by: str = "operator"


async def _execute_approved_self_healing_action(
    approval: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch an approved mutation to the tool service and persist its outcome."""
    approval_id = approval["id"]
    payload = {
        "approval_id": approval_id,
        "action": approval["action"],
        "parameters": approval.get("parameters") or {},
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.agent_http_timeout_seconds
        ) as client:
            response = await client.post(
                f"{settings.tool_service_url.rstrip('/')}/k8s/actions/execute",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
        await approval_client.record_execution(
            approval_id,
            status="succeeded",
            result=result,
        )
        return result
    except Exception as exc:
        logger.error(
            "Self-healing callback failed for approval %s: %s", approval_id, exc
        )
        try:
            await approval_client.record_execution(
                approval_id,
                status="failed",
                error=str(exc),
            )
        except ApprovalServiceError as record_exc:
            logger.warning(
                "Could not persist self-healing callback failure: %s", record_exc
            )
        raise HTTPException(
            status_code=502, detail=f"Self-healing callback failed: {exc}"
        ) from exc


@app.post("/approvals")
async def create_tool_approval(
    request: ToolApprovalRequest,
    api_key: str = Depends(verify_api_key),
):
    """Create an approval request through the authenticated Gateway."""
    try:
        return await guardrail_client.request_approval(
            request.tool_name,
            request.action,
            request.parameters,
        )
    except GuardrailServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/approvals/{approval_id}")
async def get_tool_approval(
    approval_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Return the current status of an operator approval."""
    try:
        return await guardrail_client.get_approval(approval_id)
    except GuardrailServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/approvals/{approval_id}/approve")
async def approve_tool_action(
    approval_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Approve a pending tool action."""
    try:
        return await guardrail_client.decide_approval(
            approval_id,
            approved=True,
            decided_by="operator",
        )
    except GuardrailServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/self-healing/approvals")
async def create_self_healing_approval(
    request: SelfHealingApprovalRequest,
    api_key: str = Depends(verify_api_key),
):
    """Create a durable approval for an explicitly supported K8s mutation."""
    if request.action not in SELF_HEALING_ACTIONS:
        raise HTTPException(status_code=422, detail="Unsupported self-healing action")

    try:
        verdict = await guardrail_client.guard_tool(
            tool_name="k8s",
            action=request.action,
            parameters=request.parameters,
        )
        if verdict.get("verdict") == "BLOCK":
            raise HTTPException(
                status_code=403,
                detail=verdict.get("reason", "Action blocked by guardrail"),
            )

        approval = await approval_client.create_approval(
            task_id=request.task_id or f"manual:{uuid.uuid4()}",
            agent="k8s",
            action=request.action,
            parameters=request.parameters,
            reason=verdict.get("reason"),
        )
        return {
            "requires_approval": True,
            "approval": approval,
        }
    except GuardrailServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ApprovalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/self-healing/approvals")
async def list_self_healing_approvals(
    api_key: str = Depends(verify_api_key),
):
    """List durable self-healing approvals for the Dashboard."""
    try:
        return await approval_client.list_approvals()
    except ApprovalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/self-healing/approvals/{approval_id}")
async def get_self_healing_approval(
    approval_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Return durable decision and callback state for one mutation."""
    try:
        return await approval_client.get_approval(approval_id)
    except ApprovalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/self-healing/approvals/{approval_id}/approve")
async def approve_self_healing_action(
    approval_id: str,
    decision: SelfHealingApprovalDecision = SelfHealingApprovalDecision(),
    api_key: str = Depends(verify_api_key),
):
    """Approve and immediately dispatch a Kubernetes mutation callback."""
    try:
        approval = await approval_client.approve(approval_id, decision.decided_by)
    except ApprovalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    execution = await _execute_approved_self_healing_action(approval)
    return {
        "approval": approval,
        "execution": execution,
    }


@app.post("/self-healing/approvals/{approval_id}/reject")
async def reject_self_healing_action(
    approval_id: str,
    decision: SelfHealingApprovalDecision = SelfHealingApprovalDecision(),
    api_key: str = Depends(verify_api_key),
):
    """Reject a pending Kubernetes mutation."""
    try:
        return await approval_client.reject(approval_id, decision.decided_by)
    except ApprovalServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/session/{session_id}/approve-task/{task_id}")
async def approve_session_task(
    session_id: str,
    task_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Mark a task as approved in the session memory."""
    from shared.memory import get_session_memory

    memory = get_session_memory(session_id)
    await memory.add_approved_task(task_id)
    return {
        "status": "success",
        "message": f"Task {task_id} marked as approved for session {session_id}",
    }


# ──── Session Management ────


@app.post("/session")
async def create_session(
    api_key: str = Depends(verify_api_key),
):
    """Create new session"""
    session_id = str(uuid.uuid4())
    return {
        "session_id": session_id,
        "created_at": datetime.utcnow().isoformat(),
    }


@app.get("/session/{session_id}/history")
async def get_session_history(
    session_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get session conversation history"""
    from shared.memory import get_session_memory

    session_memory = get_session_memory(session_id)
    history = await session_memory.get()

    return {
        "session_id": session_id,
        "history": history,
        "count": len(history),
    }


# ──---- Root endpoint ----


@app.get("/")
async def root():
    """API documentation"""
    return {
        "name": "Personal AI Agent Gateway",
        "version": settings.app_version,
        "endpoints": {
            "health": "GET /health",
            "execute": "POST /execute (requires API key)",
            "execute_async": "POST /execute-async (requires API key)",
            "approvals": "POST /approvals (requires API key)",
            "self_healing_approvals": "POST /self-healing/approvals (requires API key)",
            "session": "POST /session",
            "history": "GET /session/{session_id}/history",
        },
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


if __name__ == "__main__":
    import uvicorn
    from shared.config import get_bind_host

    uvicorn.run(
        "main:app",
        host=get_bind_host(),
        port=8000,
        reload=settings.debug,
    )
