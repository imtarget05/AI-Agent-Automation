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
if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=static_dir), name="assets")


@app.get("/config")
async def get_config():
    """Return frontend configuration"""
    return {
        "gateway_url": settings.dashboard_gateway_url,
        "env": settings.env,
        "version": settings.app_version
    }


@app.get("/", include_in_schema=False)
async def serve_dashboard():
    """Serve the main dashboard"""
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "Dashboard assets not found. Run npm build in dashboard directory."
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "service": "dashboard"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=get_bind_host(), port=8006)
