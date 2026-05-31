"""
Computer Use Module API
"""

import logging
from fastapi import FastAPI, HTTPException, status
from shared.config import get_bind_host
from contextlib import asynccontextmanager

from shared.models import ComputerTask, ComputerResult
from apps.computer_use.agent import ComputerUseAgent

logger = logging.getLogger(__name__)

# ──---- Lifecycle ----


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("💻 Starting Computer Use Agent Module")
    yield
    logger.info("🛑 Shutting down Computer Use Agent")


# ──---- App ----

app = FastAPI(
    title="Computer Use Agent",
    description="Desktop automation and UI control",
    version="0.1.0",
    lifespan=lifespan,
)

# Global agent
_agent: ComputerUseAgent = None


async def get_agent() -> ComputerUseAgent:
    """Get or create agent"""
    global _agent
    if _agent is None:
        _agent = ComputerUseAgent()
        await _agent.initialize()
    return _agent


# ──---- Endpoints ----


@app.post("/execute", response_model=ComputerResult)
async def execute_computer_task(task: ComputerTask):
    """
    Execute a computer use task

    Example request:
    ```json
    {
        "objective": "Open Chrome and navigate to google.com",
        "app_name": "Chrome",
        "steps": [
            "hotkey win",
            "type chrome",
            "hotkey return",
            "wait 2"
        ]
    }
    ```

    The agent will use Anthropic Computer Use API if available,
    otherwise fallback to PyAutoGUI
    """
    agent = await get_agent()

    try:
        result = await agent.execute(task)
        return result
    except Exception as e:
        logger.error(f"Task execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.post("/screenshot", response_model=ComputerResult)
async def take_screenshot():
    """
    Take a screenshot of current desktop
    """
    agent = await get_agent()
    task = ComputerTask(objective="Take screenshot")

    try:
        result = await agent.execute(task)
        return result
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.post("/click")
async def click_ui(x: int, y: int, description: str = ""):
    """Click at specific screen position"""
    agent = await get_agent()
    task = ComputerTask(
        objective=f"Click at ({x}, {y}) {description}", steps=[f"click {x} {y}"]
    )

    try:
        result = await agent.execute(task)
        return result
    except Exception as e:
        logger.error(f"Click failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "service": "computer_use_agent"}


@app.get("/")
async def root():
    """API info"""
    return {
        "name": "Computer Use Agent Module",
        "endpoints": {
            "execute": "POST /execute",
            "screenshot": "POST /screenshot",
            "click": "POST /click",
            "health": "GET /health",
        },
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=get_bind_host(),
        port=8004,
        reload=False,
    )
