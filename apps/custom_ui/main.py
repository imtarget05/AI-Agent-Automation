import os
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from shared.config import get_settings

# Configuration
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://gateway:8000/execute")

# --- Pydantic Models ---
class TaskRequest(BaseModel):
    prompt: str

class TaskResponse(BaseModel):
    response: dict

# --- FastAPI App ---
app = FastAPI(
    title="Custom UI Backend",
    description="Backend service for the custom agent UI.",
    version="1.0.0"
)

# --- API Endpoints ---
@app.post("/api/submit_task", response_model=TaskResponse)
async def submit_task(task: TaskRequest):
    """
    Receives a prompt from the frontend, forwards it to the main gateway,
    and returns the gateway's response.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                GATEWAY_URL,
                json={"user_input": task.prompt},
                headers={
                    "Authorization": f"Bearer {get_settings().api_secret_key}",
                },
                timeout=60.0,
            )
            response.raise_for_status()
            return {"response": response.json()}
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error connecting to the gateway: {e}"
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Error response from gateway: {e.response.text}"
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok"}

# --- Static File Serving ---
# This section serves the built React frontend
static_dir = os.path.join(os.path.dirname(__file__), "frontend", "dist")

if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_react_app(full_path: str):
        """Serve the React application"""
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "index.html not found"}
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {"message": "Custom UI backend is running, but the frontend has not been built yet."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
