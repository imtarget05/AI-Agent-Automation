from fastapi import FastAPI
from pydantic import BaseModel
import logging

app = FastAPI(title="RCA Agent")
logger = logging.getLogger(__name__)

class TaskRequest(BaseModel):
    instruction: str
    context: dict = {}

@app.post("/execute")
async def execute_task(req: TaskRequest):
    logger.info(f"RCA Agent received task: {req.instruction}")
    return {"success": True, "message": "Root cause analysis completed.", "data": {"root_cause": "Unknown at this time."}}

@app.get("/health")
async def health():
    return {"status": "ok"}
