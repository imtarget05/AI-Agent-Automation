from fastapi import FastAPI, HTTPException, Body
from typing import List
import uuid
from datetime import datetime
from .models import ApprovalRequest, ApprovalStatus
from .store import get_store

app = FastAPI(title="Approval Service")
store = get_store()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/approvals", response_model=ApprovalRequest)
async def create_approval(
    task_id: str = Body(..., embed=True),
    agent: str = Body(..., embed=True),
    action: str = Body(..., embed=True),
    parameters: dict = Body(None, embed=True),
    reason: str = Body(None, embed=True),
):
    approval_id = str(uuid.uuid4())
    approval = ApprovalRequest(
        id=approval_id,
        task_id=task_id,
        agent=agent,
        action=action,
        parameters=parameters,
        reason=reason,
    )
    store.add(approval)
    return approval

@app.get("/approvals", response_model=List[ApprovalRequest])
async def list_approvals():
    return store.list_all()

@app.get("/approvals/{approval_id}", response_model=ApprovalRequest)
async def get_approval(approval_id: str):
    approval = store.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval

@app.post("/approvals/{approval_id}/approve")
async def approve(approval_id: str, decided_by: str = Body(..., embed=True)):
    approval = store.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    
    approval.status = ApprovalStatus.APPROVED
    approval.decided_at = datetime.utcnow()
    approval.decided_by = decided_by
    store.update(approval)
    return approval

@app.post("/approvals/{approval_id}/reject")
async def reject(approval_id: str, decided_by: str = Body(..., embed=True)):
    approval = store.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    
    approval.status = ApprovalStatus.REJECTED
    approval.decided_at = datetime.utcnow()
    approval.decided_by = decided_by
    store.update(approval)
    return approval
