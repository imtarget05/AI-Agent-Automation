from fastapi import FastAPI
from pydantic import BaseModel
import logging

app = FastAPI(title="Report Agent")
logger = logging.getLogger(__name__)

class TaskRequest(BaseModel):
    instruction: str
    context: dict = {}

@app.post("/execute")
async def execute_task(req: TaskRequest):
    logger.info(f"Report Agent received task: {req.instruction}")
    return {
        "success": True, 
        "message": "Incident report generated.", 
        "data": {
            "report_markdown": "# Incident Report\n\n**Status**: Resolved\n\n**Summary**: ...",
            "report_html": "<h1>Incident Report</h1><p><b>Status</b>: Resolved</p>"
        }
    }

@app.get("/health")
async def health():
    return {"status": "ok"}
