from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ApprovalRequest(BaseModel):
    id: str
    task_id: str
    agent: str
    action: str
    parameters: Optional[dict] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    execution_result: Optional[dict] = None
    execution_error: Optional[str] = None
    executed_at: Optional[datetime] = None
