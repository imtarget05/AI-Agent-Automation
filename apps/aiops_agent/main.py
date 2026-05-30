from fastapi import FastAPI
from pydantic import BaseModel
import logging

app = FastAPI(title="AIOps Agent")
logger = logging.getLogger(__name__)

class TaskRequest(BaseModel):
    instruction: str
    context: dict = {}

@app.post("/execute")
async def execute_task(req: TaskRequest):
    logger.info(f"AIOps Agent received task: {req.instruction}")
    return {"success": True, "message": "Analyzed metrics and logs for anomalies.", "data": {"anomalies": []}}

@app.get("/health")
async def health():
    return {"status": "ok"}
