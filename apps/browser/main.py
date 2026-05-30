"""
Browser Module API - Expose browser automation as a service
"""
import logging
from fastapi import FastAPI, HTTPException, status
from contextlib import asynccontextmanager

from shared.models import BrowserTask, BrowserResult
from apps.browser.agent import BrowserAgent

logger = logging.getLogger(__name__)

# ──---- Lifecycle ----

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🌐 Starting Browser Agent Module")
    yield
    logger.info("🛑 Shutting down Browser Agent")


# ──---- App ----

app = FastAPI(
    title="Browser Agent",
    description="Automated web browsing and data extraction",
    version="0.1.0",
    lifespan=lifespan,
)

# Global agent instance
_browser_agent: BrowserAgent = None


async def get_agent() -> BrowserAgent:
    """Get or create browser agent"""
    global _browser_agent
    if _browser_agent is None:
        _browser_agent = BrowserAgent()
        await _browser_agent.initialize()
    return _browser_agent


# ──---- Endpoints ----

@app.post("/execute", response_model=BrowserResult)
async def execute_browser_task(task: BrowserTask):
    """
    Execute a browser automation task

    Example request:
    ```json
    {
        "url": "https://shopee.vn/search?q=iphone15",
        "instruction": "Extract product names and prices",
        "extract_fields": ["name", "price", "url"]
    }
    ```
    """
    agent = await get_agent()

    try:
        result = await agent.execute(task)
        return result
    except Exception as e:
        logger.error(f"Task execution failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.post("/search", response_model=BrowserResult)
async def search_web(query: str, extract_fields: list[str] = None):
    """
    Search the web and extract structured data

    Example:
    - query: "iPhone 15 price"
    - extract_fields: ["name", "price", "rating"]
    """
    agent = await get_agent()
    task = BrowserTask(
        search_query=query,
        instruction=f"Search and extract {', '.join(extract_fields or ['name', 'price'])}",
        extract_fields=extract_fields,
    )

    try:
        result = await agent.execute(task)
        return result
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "ok", "service": "browser_agent"}


@app.get("/")
async def root():
    """API info"""
    return {
        "name": "Browser Agent Module",
        "endpoints": {
            "execute": "POST /execute",
            "search": "POST /search",
            "health": "GET /health",
        },
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=False,
    )
