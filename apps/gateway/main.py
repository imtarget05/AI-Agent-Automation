"""
FastAPI Gateway - Main entry point for all requests
"""
import uuid
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthCredentials
from pydantic import BaseModel

from shared.config import get_settings
from shared.models import TaskRequest, TaskResponse, AgentState
from shared.memory import get_long_term_memory
from apps.gateway.orchestrator import get_orchestrator

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

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


async def verify_api_key(credentials: HTTPAuthCredentials = Depends(security)) -> str:
    """Verify API key from Authorization header"""
    if credentials.credentials != settings.api_secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key"
        )
    return credentials.credentials


# ──── Health Check ────

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.app_version,
    }


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

    try:
        orchestrator = get_orchestrator()
        result = await orchestrator.execute(request.user_input, session_id)

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
    session_id: str = None
    callback_url: str = None  # Webhook to call when done


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

    async def run_task():
        """Run in background"""
        orchestrator = get_orchestrator()
        result = await orchestrator.execute(request.user_input, session_id)

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
