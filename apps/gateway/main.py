"""
FastAPI Gateway - Main entry point for all requests
"""

import uuid
import asyncio
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from shared.approvals import ApprovalClient, ApprovalServiceError
from shared.config import get_settings
from shared.guardrails import GuardrailClient, GuardrailServiceError
from shared.open_source_knowledge import seed_open_source_knowledge
from shared.models import ModuleType, TaskRequest, TaskResponse
from shared.memory import get_long_term_memory
from shared.mcp import get_mcp_manager
from shared.internal_auth import get_internal_service_headers
from shared import job_store as job_store_module
from shared.url_security import validate_outbound_http_url
from shared.observability.tracing import (
    get_current_trace_id,
    init_tracing,
    instrument_fastapi,
    start_span,
)
from shared.observability.logging import (
    clear_log_context,
    configure_logging,
    get_logger,
    set_log_context,
)
from apps.gateway.orchestrator import get_orchestrator

configure_logging(service="gateway")
logger = get_logger(__name__)

settings = get_settings()
guardrail_client = GuardrailClient()
approval_client = ApprovalClient()
SELF_HEALING_ACTIONS = {
    "restart_deployment",
    "scale_deployment",
    "delete_pod",
}
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
        await validate_outbound_http_url(callback_url)
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
    # Initialise observability before anything else so startup spans are captured
    init_tracing(service_name=settings.otel_service_name, enabled=settings.otel_enabled)
    instrument_fastapi(app)

    logger.info("🚀 Starting Personal AI Agent Gateway")
    # Register MCP servers without spawning subprocesses. Connections stay lazy.
    mcp_manager = get_mcp_manager()
    if settings.mcp_enabled:
        for name, config in settings.mcp_servers.items():
            try:
                await mcp_manager.register_server(
                    name=name,
                    command=config["command"],
                    args=config.get("args"),
                    env=config.get("env"),
                )
            except Exception as exc:
                logger.error("Failed to register MCP server %s: %s", name, exc)

    # Initialize long-term memory collection
    try:
        await get_long_term_memory().init()
    except Exception as e:
        logger.warning(f"Long-term memory init failed: {e}")

    async def _seed_open_source() -> None:
        try:
            seeded = await seed_open_source_knowledge(
                force=settings.open_source_seed_force,
            )
            logger.info(
                "Seeded open-source knowledge: %d repo docs, %d chunks",
                seeded.get("repos_indexed", 0),
                seeded.get("chunks_indexed", 0),
            )
        except Exception as e:
            logger.warning(f"Open-source knowledge seeding failed: {e}")

    if settings.open_source_seed_enabled:
        if settings.open_source_seed_background:
            asyncio.create_task(_seed_open_source())
        else:
            await _seed_open_source()

    yield
    # Shutdown logic
    logger.info("🛑 Shutting down")
    await get_mcp_manager().close_all()


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


@app.middleware("http")
async def correlation_context_middleware(request: Request, call_next):
    """Attach request correlation IDs to logs, response headers, and spans."""
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    workflow_id = request.headers.get("x-workflow-id", "")
    session_id = request.headers.get("x-session-id", "")
    tenant_id = request.headers.get("x-tenant-id", "")
    user_id = request.headers.get("x-user-id", "")

    set_log_context(
        request_id=request_id,
        workflow_id=workflow_id,
        session_id=session_id,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    with start_span(
        "gateway.http_request",
        {
            "request_id": request_id,
            "workflow_id": workflow_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "http.method": request.method,
            "http.route": request.url.path,
        },
    ) as span:
        try:
            response = await call_next(request)
            span.set_attribute("status", "success")
            span.set_attribute("http.status_code", response.status_code)
            response.headers["x-request-id"] = request_id
            if workflow_id:
                response.headers["x-workflow-id"] = workflow_id
            if trace_id := get_current_trace_id():
                response.headers["x-trace-id"] = trace_id
            return response
        except Exception as exc:
            span.set_attribute("status", "error")
            span.set_attribute("error_type", type(exc).__name__)
            raise
        finally:
            clear_log_context()

# ──── Security ────
security = HTTPBearer()


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Verify API key from Authorization header"""
    if not secrets.compare_digest(
        credentials.credentials,
        get_settings().api_secret_key,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key"
        )
    return credentials.credentials


async def ensure_safe_input(prompt: str) -> str:
    """Reject unsafe prompts and return the masked form for downstream LLMs."""
    try:
        verdict = await guardrail_client.guard_input(prompt)
    except GuardrailServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not verdict.get("safe"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=verdict.get("reason", "Input rejected by guardrail service"),
        )
    return verdict.get("anonymized_prompt") or prompt


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


@app.get("/mcp/tools")
async def list_mcp_tools(api_key: str = Depends(verify_api_key)):
    """List tools from configured MCP servers, including connection errors."""
    if not settings.mcp_enabled:
        raise HTTPException(status_code=404, detail="MCP integration is disabled")
    return await get_mcp_manager().inspect_tools()


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
    logger.info(
        "Received incident for analysis with fields: %s",
        sorted(request.incident_data),
    )

    # We convert the structured JSON into a natural language request for the manager
    # Or bypass manager and execute an AIOps workflow directly.
    # For now, we will construct a prompt for the manager to plan the workflow.
    user_input = f"Incident occurred: {request.incident_data}. Please analyze anomalies, find root cause, and draft an email report."
    sanitized_input = await ensure_safe_input(user_input)

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
            user_input=sanitized_input,
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
    sanitized_input = await ensure_safe_input(request.user_input)

    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.execute(
            sanitized_input,
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
    sanitized_input = await ensure_safe_input(request.user_input)
    if request.callback_url:
        try:
            await validate_outbound_http_url(request.callback_url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    job_store = job_store_module.get_job_store()
    await job_store.create(task_id, sanitized_input, session_id)

    async def run_task():
        """Run in background"""
        started_at = datetime.utcnow()
        await job_store.mark_running(task_id)

        orchestrator = get_orchestrator()
        try:
            run_result = await orchestrator.execute(
                sanitized_input,
                session_id,
                allowed_modules=request.modules,
            )
            serialized_result = _serialize_task_response(run_result)
            await job_store.mark_done(
                task_id,
                serialized_result,
                (datetime.utcnow() - started_at).total_seconds(),
            )

            if request.callback_url:
                await _notify_callback(
                    request.callback_url,
                    {
                        "task_id": task_id,
                        "session_id": session_id,
                        "status": "completed",
                        "result": serialized_result,
                        "error": run_result.get("error"),
                    },
                )
        except Exception as exc:
            logger.error("Async task %s failed: %s", task_id, exc, exc_info=True)
            await job_store.mark_error(task_id, str(exc))

            if request.callback_url:
                await _notify_callback(
                    request.callback_url,
                    {
                        "task_id": task_id,
                        "session_id": session_id,
                        "status": "failed",
                        "result": None,
                        "error": str(exc),
                    },
                )

        logger.info(f"Async task {task_id} completed")

    background_tasks.add_task(run_task)

    return {
        "task_id": task_id,
        "job_id": task_id,
        "session_id": session_id,
        "status": "queued",
        "poll_url": f"/tasks/{task_id}",
        "message": f"Task queued. Poll /tasks/{task_id} for results",
    }


@app.get("/task-status/{task_id}")
async def get_task_status(
    task_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get status of async task"""
    task = await job_store_module.get_job_store().get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task.model_dump(mode="json")


@app.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Return an async job record from the TTL-backed store."""
    return await get_task_status(task_id, api_key)


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
                headers=get_internal_service_headers(),
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
            "mcp_tools": "GET /mcp/tools (requires API key)",
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
