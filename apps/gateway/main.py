"""
FastAPI Gateway - Main entry point for all requests
"""
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Optional

from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from shared.config import get_settings
from shared.guardrails import GuardrailClient, GuardrailServiceError
from shared.models import ModuleType, TaskRequest, TaskResponse
from shared.memory import get_long_term_memory
from apps.gateway.orchestrator import get_orchestrator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()
guardrail_client = GuardrailClient()

# ──── Lifecycle ────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic"""
    logger.info("🚀 Starting Personal AI Agent Gateway")
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


async def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify API key from Authorization header"""
    if credentials.credentials != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
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
    allowed_modules = [ModuleType.AIOPS, ModuleType.TOOL, ModuleType.RAG, ModuleType.RCA, ModuleType.REPORT, ModuleType.EMAIL]

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

    async def run_task():
        """Run in background"""
        orchestrator = get_orchestrator()
        result = await orchestrator.execute(
            request.user_input,
            session_id,
            allowed_modules=request.modules,
        )

        # TODO: Store result in database by task_id
        # TODO: Call callback_url webhook if provided

        logger.info(f"Async task {task_id} completed")

    background_tasks.add_task(run_task)

    return {
        "task_id": task_id,
        "session_id": session_id,
        "status": "queued",
        "message": f"Task queued. Poll /task-status/{task_id} for results"
    }


@app.get("/task-status/{task_id}")
async def get_task_status(
    task_id: str,
    api_key: str = Depends(verify_api_key),
):
    """Get status of async task"""
    # TODO: Implement database lookup
    return {
        "task_id": task_id,
        "status": "pending",
        "message": "Task status lookup not yet implemented"
    }


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


@app.post("/approvals/{approval_id}/decision")
async def decide_tool_approval(
    approval_id: str,
    decision: ToolApprovalDecision,
    api_key: str = Depends(verify_api_key),
):
    """Approve or reject a pending tool action."""
    try:
        return await guardrail_client.decide_approval(
            approval_id,
            decision.approved,
            decision.decided_by,
        )
    except GuardrailServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
            "session": "POST /session",
            "history": "GET /session/{session_id}/history",
        },
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
