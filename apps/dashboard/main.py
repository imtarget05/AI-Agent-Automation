"""
Dashboard Frontend Service

Serves the web-based monitoring dashboard with real-time updates.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from shared.config import get_settings, get_bind_host

app = FastAPI(
    title="Dashboard", description="System monitoring dashboard", version="1.0.0"
)

settings = get_settings()

# Serve static files
static_dir = os.path.join(os.path.dirname(__file__), "static")

@app.get("/config")
async def get_config():
    """Return frontend configuration"""
    return {
        "gateway_url": settings.dashboard_gateway_url,
        "env": settings.env,
        "version": settings.app_version,
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "dashboard"}

# Mount static files at root after explicit API routes
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=get_bind_host(), port=8006)
